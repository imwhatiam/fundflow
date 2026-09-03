from datetime import date, datetime
from unittest.mock import Mock, patch

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from kaipanla.management.commands.fetch_kaipanla_sector_fund_flow import Command
from kaipanla.models import (
    KaipanlaSectorFundFlowSnapshot,
    KaipanlaSectorFundFlowSnapshotStatus,
)
from kaipanla.services.intraday_builders import (
    build_kaipanla_intraday_payload,
    select_sector_series,
)
from kaipanla.services.intraday_service import query_kaipanla_intraday
from kaipanla.services.parser import optional_number, parse_sector_row
from kaipanla.services.ranking_fetcher import KaipanlaRankingFetcher
from kaipanla.services.snapshot_writer import model_values, save_kaipanla_snapshot
from kaipanla.services.trading_time import floor_to_15min, trading_slots_for_day
from kaipanla.services.types import KaipanlaSectorFundFlowFetchResult
from kaipanla.urls import urlpatterns
from kaipanla.views import KaipanlaSectorIntradayView, KaipanlaSectorListView


def kpl_row(code="801464", value=33.33):
    return [
        code,  # 0 父代码
        f"板块{code}",  # 1 父板块
        10509,  # 2 强度
        2.526,  # 3 涨幅
        0.5,  # 4 涨速
        1226.46,  # 5 成交额
        value,  # 6 主力净额
        153.08,  # 7 主力买
        -119.75,  # 8 主力卖
        1.316,  # 9 量比
        41211.11,  # 10 流通市值
        None,  # 11 未用
        14.40,  # 12 300万大单净额
        49219.72,  # 13 总市值
        None,  # 14 机构增仓
        None,  # 15 2026平均PE
        None,  # 16 2027平均PE
        10509,  # 17 强度(重复)
        2.526,  # 18 涨幅(重复)
    ]


def kpl_response(page=0, count=270, rows=None, time_value=1750000000, day=None):
    return {
        "errcode": 0,
        "Count": count,
        "Time": time_value,
        "Day": [day or "2026-09-03"],
        "list": rows if rows is not None else [kpl_row()],
    }


class KaipanlaSettingsTests(SimpleTestCase):
    def test_app_is_installed_and_has_an_independent_database(self):
        self.assertIn("kaipanla", settings.INSTALLED_APPS)
        self.assertIn("kaipanla", settings.DATABASES)
        self.assertNotEqual(
            settings.DATABASES["kaipanla"]["NAME"],
            settings.DATABASES["default"]["NAME"],
        )
        self.assertIn("kaipanla.db_router.KaipanlaRouter", settings.DATABASE_ROUTERS)

    def test_credentials_come_from_environment(self):
        self.assertEqual(settings.KAIPANLA_USER_ID, "")
        self.assertEqual(settings.KAIPANLA_TOKEN, "")
        self.assertEqual(settings.KAIPANLA_DEVICE_ID, "")


class KaipanlaParserTests(SimpleTestCase):
    def test_parses_verified_nineteen_column_row(self):
        parsed = parse_sector_row(kpl_row())
        self.assertEqual(parsed["sector_code"], "801464")
        self.assertEqual(parsed["sector_name"], "板块801464")
        self.assertEqual(parsed["change_pct"], 2.526)
        self.assertEqual(parsed["main_net_inflow"], 33.33)
        self.assertEqual(parsed["large_order_net_inflow"], 14.40)
        self.assertEqual(parsed["total_market_cap"], 49219.72)

    def test_rejects_row_without_code_or_net_inflow(self):
        self.assertIsNone(parse_sector_row([None, "x", 1, 2, 3, 4, None]))
        self.assertIsNone(parse_sector_row(["", "x", 1, 2, 3, 4, 5]))

    def test_optional_number_normalizes_empty_tokens(self):
        for token in ("-", "--", "", "null", "NULL", None):
            self.assertIsNone(optional_number(token))
        self.assertEqual(optional_number("12.3"), "12.3")


class KaipanlaRankingFetcherTests(SimpleTestCase):
    def fetcher(self, http_client, sleep=None):
        return KaipanlaRankingFetcher(http_client=http_client, sleep=sleep or Mock())

    def test_paginates_until_index_reaches_count(self):
        http_client = Mock()
        http_client.post_json.side_effect = [
            kpl_response(page=0, count=60, rows=[kpl_row("1", 1)]),
            kpl_response(page=1, count=60, rows=[kpl_row("2", 2)]),
            kpl_response(page=2, count=60, rows=[]),
        ]

        result = self.fetcher(http_client).fetch_sector_fund_flow()

        self.assertEqual(http_client.post_json.call_count, 2)
        self.assertTrue(result.fetch_succeeded)
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(result.source_trade_date, "2026-09-03")

    def test_dedupes_by_sector_code(self):
        http_client = Mock()
        http_client.post_json.side_effect = [
            kpl_response(page=0, count=30, rows=[kpl_row("1", 1), kpl_row("1", 99)]),
        ]

        result = self.fetcher(http_client).fetch_sector_fund_flow()

        self.assertEqual(len(result.rows), 1)

    def test_retries_then_fails_cleanly(self):
        http_client = Mock()
        http_client.post_json.side_effect = requests.RequestException("down")
        sleep = Mock()

        result = self.fetcher(http_client, sleep=sleep).fetch_sector_fund_flow()

        self.assertFalse(result.fetch_succeeded)
        self.assertEqual(result.rows, [])
        self.assertEqual(http_client.post_json.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_business_error_is_not_success(self):
        http_client = Mock()
        http_client.post_json.return_value = {"errcode": 100, "errmsg": "token 过期"}

        result = self.fetcher(http_client).fetch_sector_fund_flow()

        self.assertFalse(result.fetch_succeeded)


class KaipanlaSnapshotWriterTests(TestCase):
    databases = {"default", "kaipanla"}
    def test_writes_snapshot_and_status_to_kaipanla_database(self):
        result = KaipanlaSectorFundFlowFetchResult(
            rows=[parse_sector_row(kpl_row())],
            fetch_succeeded=True,
            source_timestamp=1750000000,
            source_trade_date="2026-09-03",
        )
        snapshot_time = timezone.make_aware(datetime(2026, 9, 3, 10, 0))

        saved = save_kaipanla_snapshot(snapshot_time=snapshot_time, fetch_result=result)

        self.assertTrue(saved.saved)
        self.assertEqual(saved.row_count, 1)
        self.assertTrue(
            KaipanlaSectorFundFlowSnapshot.objects.using("kaipanla").filter(
                sector_code="801464"
            ).exists()
        )
        status = KaipanlaSectorFundFlowSnapshotStatus.objects.using("kaipanla").get(
            snapshot_time=snapshot_time
        )
        self.assertTrue(status.fetch_succeeded)

    def test_model_values_strips_ephemeral_fields(self):
        values = model_values(
            {"sector_code": "1", "main_net_inflow": 1, "source_timestamp": 1, "source_trade_date": "x"}
        )
        self.assertNotIn("source_timestamp", values)
        self.assertNotIn("source_trade_date", values)

    def test_empty_rows_do_not_write(self):
        result = KaipanlaSectorFundFlowFetchResult(rows=[], fetch_succeeded=False)
        saved = save_kaipanla_snapshot(
            snapshot_time=timezone.make_aware(datetime(2026, 9, 3, 10, 0)),
            fetch_result=result,
        )
        self.assertFalse(saved.saved)


class KaipanlaIntradayBuilderTests(SimpleTestCase):
    trade_date = date(2026, 9, 3)

    @staticmethod
    def local_datetime(hour, minute):
        return timezone.make_aware(datetime(2026, 9, 3, hour, minute))

    def test_builds_payload_and_selects_leaders(self):
        time_axis = [
            self.local_datetime(9, 30),
            self.local_datetime(9, 45),
        ]
        snapshot_rows = [
            {"sector_code": "A", "sector_name": "流入", "snapshot_time": time_axis[0], "main_net_inflow": 200_000_000},
            {"sector_code": "A", "sector_name": "流入", "snapshot_time": time_axis[1], "main_net_inflow": 300_000_000},
            {"sector_code": "B", "sector_name": "流出", "snapshot_time": time_axis[1], "main_net_inflow": -100_000_000},
        ]
        status_rows = [
            {"snapshot_time": time_axis[1], "fetch_succeeded": True},
        ]

        payload = build_kaipanla_intraday_payload(
            trade_date=self.trade_date,
            time_axis=time_axis,
            snapshot_rows=snapshot_rows,
            status_rows=status_rows,
            inflow_top=1,
            outflow_top=1,
        )

        self.assertEqual(payload["time_points"], ["09:30", "09:45"])
        self.assertEqual({item["code"] for item in payload["series"]}, {"A", "B"})
        self.assertFalse(payload["stale"])

    def test_missing_tick_is_stale(self):
        time_axis = [self.local_datetime(9, 30), self.local_datetime(9, 45)]
        snapshot_rows = [
            {"sector_code": "A", "sector_name": "A", "snapshot_time": time_axis[0], "main_net_inflow": 100_000_000},
        ]
        status_rows = [{"snapshot_time": time_axis[0], "fetch_succeeded": True}]

        payload = build_kaipanla_intraday_payload(
            trade_date=self.trade_date,
            time_axis=time_axis,
            snapshot_rows=snapshot_rows,
            status_rows=status_rows,
            inflow_top=1,
            outflow_top=0,
        )

        self.assertTrue(payload["stale"])

    def test_select_sector_series_direction(self):
        selected = select_sector_series(
            [
                {"code": "p1", "latest_net_inflow": 9},
                {"code": "p2", "latest_net_inflow": 7},
                {"code": "n1", "latest_net_inflow": -5},
            ],
            inflow_top=1,
            outflow_top=1,
        )
        self.assertEqual([item["code"] for item in selected], ["p1", "n1"])


class KaipanlaCommandTests(TestCase):
    databases = {"default", "kaipanla"}
    def test_command_floors_tick_and_writes(self):
        now = timezone.make_aware(datetime(2026, 9, 3, 10, 10))
        client = Mock()
        client.fetch_sector_fund_flow.return_value = KaipanlaSectorFundFlowFetchResult(
            rows=[parse_sector_row(kpl_row())],
            fetch_succeeded=True,
            source_timestamp=int(timezone.make_aware(datetime(2026, 9, 3, 10, 0)).timestamp()),
        )
        with (
            patch("kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.timezone.now", return_value=now),
            patch(
                "kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaRankingFetcher",
                return_value=client,
            ),
        ):
            call_command("fetch_kaipanla_sector_fund_flow")

        snapshot = KaipanlaSectorFundFlowSnapshot.objects.using("kaipanla").get(sector_code="801464")
        self.assertEqual(timezone.localtime(snapshot.snapshot_time).strftime("%H:%M"), "10:00")

    def test_command_skips_non_trading_time(self):
        now = timezone.make_aware(datetime(2026, 9, 3, 15, 30))
        client = Mock()
        with (
            patch("kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.timezone.now", return_value=now),
            patch(
                "kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaRankingFetcher",
                return_value=client,
            ),
        ):
            call_command("fetch_kaipanla_sector_fund_flow")

        client.fetch_sector_fund_flow.assert_not_called()

    def test_command_rejects_force_option(self):
        parser = Command().create_parser("manage.py", "fetch_kaipanla_sector_fund_flow")
        with self.assertRaises(CommandError):
            parser.parse_args(["--force"])


class KaipanlaApiTests(TestCase):
    databases = {"default", "kaipanla"}
    def test_only_kaipanla_routes_are_exposed(self):
        self.assertEqual(
            {pattern.name for pattern in urlpatterns},
            {"kaipanla-sector-list", "kaipanla-sector-intraday"},
        )

    def test_intraday_api_defaults_to_five_per_direction(self):
        request = APIRequestFactory().get("/kaipanla-api/sectors/intraday/", {"date": "2026-09-03"})
        with patch(
            "kaipanla.views.query_kaipanla_intraday",
            return_value={"trade_date": "2026-09-03", "time_points": [], "series": [], "stale": True},
        ) as query_intraday:
            response = KaipanlaSectorIntradayView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        query_intraday.assert_called_once_with(
            trade_date=date(2026, 9, 3),
            inflow_top=5,
            outflow_top=5,
        )

    def test_intraday_api_clamps_limits(self):
        request = APIRequestFactory().get(
            "/kaipanla-api/sectors/intraday/",
            {"date": "2026-09-03", "inflow_top": "100", "outflow_top": "-2"},
        )
        with patch(
            "kaipanla.views.query_kaipanla_intraday",
            return_value={"time_points": [], "series": []},
        ) as query_intraday:
            KaipanlaSectorIntradayView.as_view()(request)

        query_intraday.assert_called_once_with(
            trade_date=date(2026, 9, 3),
            inflow_top=30,
            outflow_top=0,
        )

    def test_sector_list_uses_latest_snapshot(self):
        trade_date = date(2026, 9, 3)
        for code, name, minute in [("1", "早盘", 9), ("2", "午后", 13)]:
            KaipanlaSectorFundFlowSnapshot.objects.using("kaipanla").create(
                sector_code=code,
                sector_name=name,
                trade_date=trade_date,
                snapshot_time=timezone.make_aware(datetime(2026, 9, 3, minute, 0)),
                main_net_inflow=1,
            )

        response = KaipanlaSectorListView.as_view()(APIRequestFactory().get("/kaipanla-api/sectors/"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [{"code": "2", "name": "午后"}])
