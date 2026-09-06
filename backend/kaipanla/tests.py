from datetime import date, datetime
from unittest.mock import Mock, call, patch

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
from kaipanla.services.constants import (
    KAIPANLA_RANKING_PAGE_SIZE as kaipanla_page_size,
)
from kaipanla.services.intraday_builders import (
    build_kaipanla_intraday_payload,
    build_period_rankings,
    select_sector_series,
)
from kaipanla.services.intraday_cache import kaipanla_intraday_cache_key
from kaipanla.services.intraday_service import (
    query_kaipanla_intraday,
    query_kaipanla_intraday_history,
)
from kaipanla.services.parser import optional_number, parse_sector_row
from kaipanla.services.ranking_fetcher import KaipanlaRankingFetcher
from kaipanla.services.snapshot_writer import model_values, save_kaipanla_snapshot
from kaipanla.services.trading_time import (
    SNAPSHOT_INTERVAL_MINUTES as kaipanla_interval,
)
from kaipanla.services.trading_time import (
    floor_to_snapshot_interval,
    trading_slots_for_day,
    trading_slots_until,
)
from fundflow.services.trading_time import (
    SNAPSHOT_INTERVAL_MINUTES as eastmoney_interval,
)
from fundflow.services.trading_time import (
    trading_slots_for_day as eastmoney_slots_for_day,
)
from kaipanla.services.trading_calendar import trading_day_window
from kaipanla.services.types import KaipanlaSectorFundFlowFetchResult
from kaipanla.urls import urlpatterns
from kaipanla.views import (
    KaipanlaSectorIntradayHistoryView,
    KaipanlaSectorIntradayView,
    KaipanlaSectorListView,
)


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


def kpl_rows(prefix, count):
    """生成 ``count`` 条板块代码互不重复的上游行，用于构造整页数据。"""
    return [kpl_row(f"{prefix}-{i}", i) for i in range(count)]


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


class KaipanlaTradingCalendarTests(SimpleTestCase):
    def test_trading_day_window_backfills_from_a_non_trading_end_date(self):
        self.assertEqual(
            trading_day_window(date(2026, 1, 1), count=3),
            [date(2025, 12, 31), date(2025, 12, 30), date(2025, 12, 29)],
        )


class KaipanlaTradingTimeTests(SimpleTestCase):
    """锁定开盘啦 5 分钟快照刻度的契约。"""

    trade_date = date(2026, 9, 3)

    def test_day_has_fifty_five_minute_slots(self):
        slots = trading_slots_for_day(self.trade_date)
        labels = [timezone.localtime(slot).strftime("%H:%M") for slot in slots]
        self.assertEqual(len(slots), 50)
        self.assertEqual(labels[0], "09:30")
        self.assertEqual(labels[-1], "15:00")

    def test_slots_are_five_minutes_apart_and_skip_lunch_break(self):
        slots = trading_slots_for_day(self.trade_date)
        labels = [timezone.localtime(slot).strftime("%H:%M") for slot in slots]

        # 午休从 11:30 直接跳到 13:00，不产生 11:35–12:55 的刻度。
        self.assertEqual(labels[24], "11:30")
        self.assertEqual(labels[25], "13:00")
        self.assertNotIn("11:35", labels)
        self.assertNotIn("12:30", labels)

        morning = labels[:25]
        self.assertEqual(len(morning), 25)
        self.assertEqual(morning[1], "09:35")
        self.assertEqual(morning[2], "09:40")

    def test_floor_aligns_down_to_five_minutes(self):
        cases = {
            (10, 12): "10:10",
            (10, 10): "10:10",
            (10, 14): "10:10",
            (10, 4): "10:00",
            (9, 30): "09:30",
            (14, 59): "14:55",
        }
        for (hour, minute), expected in cases.items():
            with self.subTest(hour=hour, minute=minute):
                value = timezone.make_aware(datetime(2026, 9, 3, hour, minute))
                self.assertEqual(
                    floor_to_snapshot_interval(value).strftime("%H:%M"),
                    expected,
                )

    def test_slots_until_returns_only_elapsed_ticks(self):
        now = timezone.make_aware(datetime(2026, 9, 3, 9, 47))
        slots = trading_slots_until(self.trade_date, now=now)
        self.assertEqual(
            [timezone.localtime(slot).strftime("%H:%M") for slot in slots],
            ["09:30", "09:35", "09:40", "09:45"],
        )

    def test_slots_until_returns_whole_day_for_past_dates(self):
        now = timezone.make_aware(datetime(2026, 9, 4, 10, 0))
        self.assertEqual(len(trading_slots_until(self.trade_date, now=now)), 50)

    def test_slots_until_returns_empty_for_future_dates(self):
        now = timezone.make_aware(datetime(2026, 9, 2, 10, 0))
        self.assertEqual(trading_slots_until(self.trade_date, now=now), [])

    def test_eastmoney_stays_on_fifteen_minute_interval(self):
        """两个数据源的时间轴相互独立：东财必须仍为 15 分钟。"""
        self.assertEqual(kaipanla_interval, 5)
        self.assertEqual(eastmoney_interval, 15)
        self.assertEqual(len(trading_slots_for_day(self.trade_date)), 50)
        self.assertEqual(len(eastmoney_slots_for_day(self.trade_date)), 18)


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
        size = kaipanla_page_size
        http_client = Mock()
        http_client.post_json.side_effect = [
            kpl_response(page=0, count=2 * size, rows=kpl_rows("a", size)),
            kpl_response(page=1, count=2 * size, rows=kpl_rows("b", size)),
            kpl_response(page=2, count=2 * size, rows=[]),
        ]

        result = self.fetcher(http_client).fetch_sector_fund_flow()

        self.assertEqual(http_client.post_json.call_count, 2)
        self.assertTrue(result.fetch_succeeded)
        self.assertEqual(len(result.rows), 2 * size)
        self.assertEqual(result.source_trade_date, "2026-09-03")

    def test_full_universe_uses_fewer_requests_than_legacy_page_size(self):
        """270 个板块应按当前页大小分页，且请求数少于旧的每页 30 条。"""
        size = kaipanla_page_size
        count = 270
        http_client = Mock()
        pages = []
        remaining = count
        while remaining > 0:
            take = min(size, remaining)
            pages.append(kpl_response(page=len(pages), count=count, rows=kpl_rows(f"p{len(pages)}", take)))
            remaining -= take
        http_client.post_json.side_effect = pages

        result = self.fetcher(http_client).fetch_sector_fund_flow()

        self.assertTrue(result.fetch_succeeded)
        self.assertEqual(len(result.rows), count)
        self.assertEqual(http_client.post_json.call_count, -(-count // size))
        self.assertLess(http_client.post_json.call_count, -(-count // 30))

    def test_short_page_fails_instead_of_writing_partial_data(self):
        """上游超出单页上限时静默只给 8 条且 errcode 仍为 0，必须判失败而非写入残缺快照。"""
        http_client = Mock()
        http_client.post_json.side_effect = [
            kpl_response(page=0, count=270, rows=kpl_rows("x", 8)),
        ]

        result = self.fetcher(http_client).fetch_sector_fund_flow()

        self.assertFalse(result.fetch_succeeded)
        self.assertEqual(result.rows, [])
        self.assertEqual(http_client.post_json.call_count, 1)

    def test_page_size_stays_within_verified_upstream_limit(self):
        """实测上游单页上限为 80：st<=80 正常返回，st>=81 会被静默截断为 8 条。"""
        self.assertLessEqual(kaipanla_page_size, 80)

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
        payload = build_kaipanla_intraday_payload(
            trade_date=self.trade_date,
            time_axis=time_axis,
            snapshot_rows=snapshot_rows,
            inflow_top=1,
            outflow_top=1,
        )

        self.assertEqual(payload["time_points"], ["09:30", "09:45"])
        self.assertEqual({item["code"] for item in payload["series"]}, {"A", "B"})

    def test_falls_back_to_previous_tick_when_latest_is_missing(self):
        """最新刻度没有数据时，榜单与曲线沿用前一个有数据的刻度。"""
        time_axis = [self.local_datetime(9, 30), self.local_datetime(9, 45)]
        snapshot_rows = [
            {"sector_code": "A", "sector_name": "A", "snapshot_time": time_axis[0], "main_net_inflow": 100_000_000},
        ]

        payload = build_kaipanla_intraday_payload(
            trade_date=self.trade_date,
            time_axis=time_axis,
            snapshot_rows=snapshot_rows,
            inflow_top=1,
            outflow_top=0,
        )

        self.assertEqual(len(payload["series"]), 1)
        self.assertEqual(payload["series"][0]["data"], [1.0, 1.0])
        self.assertEqual(payload["series"][0]["latest_net_inflow"], 1.0)

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


class KaipanlaHistoryServiceTests(TestCase):
    databases = {"default", "kaipanla"}

    def create_snapshot(self, trade_date, hour, minute, code, value):
        return KaipanlaSectorFundFlowSnapshot.objects.using("kaipanla").create(
            sector_code=code,
            sector_name=f"板块{code}",
            trade_date=trade_date,
            snapshot_time=timezone.make_aware(datetime(trade_date.year, trade_date.month, trade_date.day, hour, minute)),
            main_net_inflow=value,
        )

    def test_uses_fixed_trading_day_window_and_keeps_missing_days_in_the_payload(self):
        latest_date = date(2026, 9, 3)
        missing_trade_date = date(2026, 9, 2)
        previous_trade_date = date(2026, 9, 1)
        excluded_date = date(2026, 8, 31)
        self.create_snapshot(latest_date, 9, 30, "OLD", 900_000_000)
        self.create_snapshot(latest_date, 15, 0, "A", 200_000_000)
        self.create_snapshot(latest_date, 15, 0, "B", 150_000_000)
        self.create_snapshot(latest_date, 15, 0, "C", -100_000_000)
        self.create_snapshot(previous_trade_date, 15, 0, "A", -300_000_000)
        self.create_snapshot(previous_trade_date, 15, 0, "B", 200_000_000)
        self.create_snapshot(previous_trade_date, 15, 0, "C", -400_000_000)
        self.create_snapshot(excluded_date, 15, 0, "EXCLUDED", 900_000_000)
        daily_payloads = [
            {
                "trade_date": "2026-09-03",
                "time_points": ["09:30", "15:00"],
                "series": [
                    {"code": "A", "name": "板块A", "latest_net_inflow": 2.0, "data": [1.0, 2.0]},
                    {"code": "B", "name": "板块B", "latest_net_inflow": 1.5, "data": [0.5, 1.5]},
                    {"code": "C", "name": "板块C", "latest_net_inflow": -1.0, "data": [-0.5, -1.0]},
                ],
            },
            {
                "trade_date": "2026-09-02",
                "time_points": [],
                "series": [],
            },
            {
                "trade_date": "2026-09-01",
                "time_points": ["09:30", "15:00"],
                "series": [
                    {"code": "A", "name": "板块A", "latest_net_inflow": -3.0, "data": [-1.0, -3.0]},
                    {"code": "B", "name": "板块B", "latest_net_inflow": 2.0, "data": [1.0, 2.0]},
                    {"code": "C", "name": "板块C", "latest_net_inflow": -4.0, "data": [-2.0, -4.0]},
                ],
            },
        ]

        with patch(
            "kaipanla.services.intraday_service.query_kaipanla_intraday",
            side_effect=daily_payloads,
        ) as query_intraday:
            payload = query_kaipanla_intraday_history(
                end_date=latest_date,
                days=3,
                inflow_top=25,
                outflow_top=25,
            )

        self.assertEqual(
            payload["items"],
            [
                {
                    "trade_date": "2026-09-03",
                    "time_points": ["15:00"],
                    "series": [
                        {"code": "A", "name": "板块A", "latest_net_inflow": 2.0, "data": [2.0]},
                        {"code": "B", "name": "板块B", "latest_net_inflow": 1.5, "data": [1.5]},
                        {"code": "C", "name": "板块C", "latest_net_inflow": -1.0, "data": [-1.0]},
                    ],
                },
                {
                    "trade_date": "2026-09-02",
                    "time_points": ["15:00"],
                    "series": [],
                },
                {
                    "trade_date": "2026-09-01",
                    "time_points": ["15:00"],
                    "series": [
                        {"code": "A", "name": "板块A", "latest_net_inflow": -3.0, "data": [-3.0]},
                        {"code": "B", "name": "板块B", "latest_net_inflow": 2.0, "data": [2.0]},
                        {"code": "C", "name": "板块C", "latest_net_inflow": -4.0, "data": [-4.0]},
                    ],
                },
            ],
        )
        self.assertEqual(
            payload["period_rankings"],
            {
                "inflows": [
                    {"code": "B", "name": "板块B", "inflow_total": 3.5, "outflow_total": 0.0, "net_inflow_total": 3.5},
                    {"code": "A", "name": "板块A", "inflow_total": 0.0, "outflow_total": 1.0, "net_inflow_total": -1.0},
                    {"code": "C", "name": "板块C", "inflow_total": 0.0, "outflow_total": 5.0, "net_inflow_total": -5.0},
                ],
                "outflows": [
                    {"code": "C", "name": "板块C", "inflow_total": 0.0, "outflow_total": 5.0, "net_inflow_total": -5.0},
                    {"code": "A", "name": "板块A", "inflow_total": 0.0, "outflow_total": 1.0, "net_inflow_total": -1.0},
                    {"code": "B", "name": "板块B", "inflow_total": 3.5, "outflow_total": 0.0, "net_inflow_total": 3.5},
                ],
            },
        )
        self.assertEqual(
            query_intraday.call_args_list,
            [
                call(trade_date=latest_date, inflow_top=25, outflow_top=25, additional_codes=("A", "B", "C")),
                call(trade_date=missing_trade_date, inflow_top=25, outflow_top=25, additional_codes=("A", "B", "C")),
                call(trade_date=previous_trade_date, inflow_top=25, outflow_top=25, additional_codes=("A", "B", "C")),
            ],
        )

    def test_period_rankings_use_full_total_order_including_non_positive_values(self):
        rankings = build_period_rankings(
            [
                {"sector_code": "A", "sector_name": "A", "main_net_inflow": 100_000_000},
                {"sector_code": "A", "sector_name": "A", "main_net_inflow": -200_000_000},
                {"sector_code": "B", "sector_name": "B", "main_net_inflow": -200_000_000},
                {"sector_code": "C", "sector_name": "C", "main_net_inflow": -300_000_000},
                {"sector_code": "D", "sector_name": "D", "main_net_inflow": -400_000_000},
                {"sector_code": "E", "sector_name": "E", "main_net_inflow": -500_000_000},
                {"sector_code": "F", "sector_name": "F", "main_net_inflow": -600_000_000},
                {"sector_code": "Z", "sector_name": "Z", "main_net_inflow": 0},
            ],
            inflow_top=3,
            outflow_top=2,
        )

        self.assertEqual([item["code"] for item in rankings["inflows"]], ["Z", "A", "B"])
        self.assertEqual([item["code"] for item in rankings["outflows"]], ["F", "E"])
        self.assertEqual(rankings["inflows"][1]["net_inflow_total"], -1.0)
        self.assertEqual(rankings["outflows"][0]["outflow_total"], 6.0)

    def test_period_leader_outside_daily_top_is_included_in_daily_series(self):
        time_axis = [
            timezone.make_aware(datetime(2026, 9, 3, 9, 30)),
            timezone.make_aware(datetime(2026, 9, 3, 9, 45)),
        ]
        payload = build_kaipanla_intraday_payload(
            trade_date=date(2026, 9, 3),
            time_axis=time_axis,
            snapshot_rows=[
                {"sector_code": "A", "sector_name": "A", "snapshot_time": time_axis[1], "main_net_inflow": 100_000_000},
                {"sector_code": "B", "sector_name": "B", "snapshot_time": time_axis[0], "main_net_inflow": -200_000_000},
            ],
            inflow_top=1,
            outflow_top=0,
            additional_codes=("B",),
        )

        self.assertEqual([item["code"] for item in payload["series"]], ["A", "B"])
        self.assertEqual(payload["series"][1]["data"], [-2.0, -2.0])

    def test_cache_key_varies_by_period_leader_codes(self):
        time_axis = [timezone.make_aware(datetime(2026, 9, 3, 15, 0))]
        common = {"trade_date": date(2026, 9, 3), "time_axis": time_axis, "data_version": 1, "inflow_top": 25, "outflow_top": 25}
        self.assertNotEqual(
            kaipanla_intraday_cache_key(**common, additional_codes=("A",)),
            kaipanla_intraday_cache_key(**common, additional_codes=("B",)),
        )


class KaipanlaCommandTests(TestCase):
    databases = {"default", "kaipanla"}
    def test_command_floors_tick_and_writes(self):
        now = timezone.make_aware(datetime(2026, 9, 3, 10, 12))
        client = Mock()
        client.fetch_sector_fund_flow.return_value = KaipanlaSectorFundFlowFetchResult(
            rows=[parse_sector_row(kpl_row())],
            fetch_succeeded=True,
            source_timestamp=int(timezone.make_aware(datetime(2026, 9, 3, 10, 10)).timestamp()),
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
        self.assertEqual(timezone.localtime(snapshot.snapshot_time).strftime("%H:%M"), "10:10")

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
            {"kaipanla-sector-list", "kaipanla-sector-intraday", "kaipanla-sector-intraday-history"},
        )

    def test_intraday_api_defaults_to_five_per_direction(self):
        request = APIRequestFactory().get("/kaipanla-api/sectors/intraday/", {"date": "2026-09-03"})
        with patch(
            "kaipanla.views.query_kaipanla_intraday",
            return_value={"trade_date": "2026-09-03", "time_points": [], "series": []},
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

    def test_intraday_history_api_delegates_a_requested_trading_day_window(self):
        request = APIRequestFactory().get(
            "/kaipanla-api/sectors/intraday/history/",
            {"date": "2026-09-03", "days": "5", "inflow_top": "25", "outflow_top": "25"},
        )
        payload = {
            "end_date": "2026-09-03",
            "items": [{"trade_date": "2026-09-03", "time_points": [], "series": []}],
        }
        with patch("kaipanla.views.query_kaipanla_intraday_history", return_value=payload) as query_history:
            response = KaipanlaSectorIntradayHistoryView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, payload)
        query_history.assert_called_once_with(
            end_date=date(2026, 9, 3),
            days=5,
            inflow_top=25,
            outflow_top=25,
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
