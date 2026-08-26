from datetime import date, datetime
from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from fundflow.management.commands.fetch_sector_fund_flow import Command
from fundflow.models import EastmoneySectorFundFlowSnapshot
from fundflow.services.aggregation import (
    aggregate_sector_intraday,
    get_sector_intraday_cache_timeout,
    get_trading_time_axis,
    select_sector_series,
)
from fundflow.services.eastmoney_client import (
    EASTMONEY_SECTOR_CLIST_UT,
    EASTMONEY_SECTOR_FS,
    SECTOR_FIELDS,
    EastmoneyClient,
)
from fundflow.services.trading_calendar import (
    is_a_share_trading_day,
    previous_a_share_trading_day,
)
from fundflow.services.trading_time import floor_to_15min, trading_slots_for_day
from fundflow.urls import urlpatterns
from fundflow.views import SectorIntradayView, SectorListView


def sector_row(code, value=100, timestamp=None):
    row = {
        "f12": code,
        "f14": f"板块{code}",
        "f2": 1000,
        "f3": 1,
        "f62": value,
        "f184": 2,
        "f66": 10,
        "f72": 20,
        "f78": 30,
        "f84": 40,
    }
    if timestamp is not None:
        row["f124"] = timestamp
    return row


class TradingCalendarTests(SimpleTestCase):
    def test_statutory_holiday_and_weekend_makeup_workday_are_not_trading_days(self):
        self.assertFalse(is_a_share_trading_day(date(2026, 1, 1)))
        # 调休周日即使被标记为工作日，A 股仍不开市。
        self.assertFalse(is_a_share_trading_day(date(2026, 1, 4)))

    def test_previous_trading_day_skips_holiday_and_weekend(self):
        self.assertEqual(previous_a_share_trading_day(date(2026, 1, 1)), date(2025, 12, 31))


class EastmoneySectorClientTests(SimpleTestCase):
    def test_request_uses_eastmoney_industry_filter_and_requested_page_size(self):
        client = EastmoneyClient(page_size=50, page_delay=0)
        with patch.object(
            client,
            "_get_with_retry",
            return_value={"data": {"total": 0, "diff": []}},
        ) as get_with_retry:
            self.assertEqual(client.fetch_all_sector_fund_flow(), [])

        params = get_with_retry.call_args.args[0]
        self.assertEqual(params["ut"], EASTMONEY_SECTOR_CLIST_UT)
        self.assertEqual(params["fs"], EASTMONEY_SECTOR_FS)
        self.assertEqual(params["fields"], SECTOR_FIELDS)
        self.assertEqual(params["fid0"], "f62")
        self.assertEqual(params["pz"], 50)

    def test_pagination_uses_actual_returned_count_until_total_is_reached(self):
        client = EastmoneyClient(page_size=200, page_delay=0)
        responses = [
            {"data": {"total": 3, "diff": [sector_row("BK0001")]}},
            {"data": {"total": 3, "diff": [sector_row("BK0002")]}},
            {"data": {"total": 3, "diff": [sector_row("BK0003")]}},
        ]
        with patch.object(client, "_get_with_retry", side_effect=responses) as fetch:
            result = client.fetch_all_sector_fund_flow()

        self.assertEqual([item["sector_code"] for item in result], ["BK0001", "BK0002", "BK0003"])
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual([call.args[0]["pn"] for call in fetch.call_args_list], [1, 2, 3])

    def test_duplicate_codes_make_the_result_unusable(self):
        client = EastmoneyClient(page_size=1, page_delay=0)
        with patch.object(
            client,
            "_get_with_retry",
            side_effect=[
                {"data": {"total": 2, "diff": [sector_row("BK0001")]}},
                {"data": {"total": 2, "diff": [sector_row("BK0001")]}},
            ],
        ):
            self.assertEqual(client.fetch_all_sector_fund_flow(), [])

    def test_partial_cleaning_is_logged_but_valid_rows_are_returned(self):
        client = EastmoneyClient(page_size=2, page_delay=0)
        incomplete_row = sector_row("BK0002")
        incomplete_row.pop("f62")
        with (
            patch.object(
                client,
                "_get_with_retry",
                return_value={
                    "data": {
                        "total": 2,
                        "diff": [sector_row("BK0001"), incomplete_row],
                    }
                },
            ),
            self.assertLogs("fundflow.services.eastmoney_client", level="WARNING") as logs,
        ):
            result = client.fetch_all_sector_fund_flow()

        self.assertEqual([item["sector_code"] for item in result], ["BK0001"])
        self.assertIn("清洗时丢弃 1 条", "\n".join(logs.output))

    def test_every_successful_page_waits_before_the_next_request_or_return(self):
        client = EastmoneyClient(page_size=1, page_delay=10)
        responses = [
            {"data": {"total": 2, "diff": [sector_row("BK0001")]}},
            {"data": {"total": 2, "diff": [sector_row("BK0002")]}},
        ]

        with (
            patch.object(client, "_get_with_retry", side_effect=responses),
            patch("fundflow.services.eastmoney_client.time.sleep") as sleep,
        ):
            client.fetch_all_sector_fund_flow()

        self.assertEqual(sleep.call_args_list, [((10,), {}), ((10,), {})])

    def test_parser_preserves_upstream_snapshot_timestamp(self):
        self.assertEqual(
            EastmoneyClient._parse_sector_row(sector_row("BK0001", timestamp=1_777_000_000)),
            {
                "sector_code": "BK0001",
                "sector_name": "板块BK0001",
                "latest_index": 1000,
                "change_pct": 1,
                "main_net_inflow": 100,
                "main_net_inflow_ratio": 2,
                "super_large_net_inflow": 10,
                "large_net_inflow": 20,
                "medium_net_inflow": 30,
                "small_net_inflow": 40,
                "source_timestamp": 1_777_000_000,
            },
        )

    def test_connection_failure_rebuilds_owned_session_before_retrying(self):
        failed_session = Mock()
        failed_session.get.side_effect = requests.exceptions.ConnectionError("proxy disconnected")
        success_response = Mock()
        success_response.json.return_value = {"data": {"total": 0, "diff": []}}
        success_session = Mock()
        success_session.get.return_value = success_response
        client = EastmoneyClient(max_retries=1, retry_backoff=0, page_delay=0)

        with patch(
            "fundflow.services.eastmoney_client.requests.Session",
            side_effect=[failed_session, success_session],
        ):
            self.assertEqual(
                client.fetch_all_sector_fund_flow(),
                [],
            )

        failed_session.close.assert_called_once()
        self.assertEqual(success_session.get.call_count, 1)


class TradingTimeTests(SimpleTestCase):
    def test_floors_live_snapshot_to_previous_quarter_hour(self):
        self.assertEqual(
            timezone.localtime(floor_to_15min(timezone.make_aware(datetime(2026, 8, 19, 9, 35)))).strftime(
                "%H:%M"
            ),
            "09:30",
        )
        self.assertEqual(
            timezone.localtime(floor_to_15min(timezone.make_aware(datetime(2026, 8, 19, 10, 10)))).strftime(
                "%H:%M"
            ),
            "10:00",
        )

    def test_generates_eighteen_standard_ticks(self):
        slots = trading_slots_for_day(date(2026, 8, 19))
        self.assertEqual(len(slots), 18)
        self.assertEqual(timezone.localtime(slots[0]).strftime("%H:%M"), "09:30")
        self.assertEqual(timezone.localtime(slots[-1]).strftime("%H:%M"), "15:00")


class SectorAggregationTests(TestCase):
    trade_date = date(2026, 8, 19)

    def setUp(self):
        cache.clear()

    @staticmethod
    def local_datetime(hour, minute):
        return timezone.make_aware(datetime(2026, 8, 19, hour, minute))

    def create_snapshot(self, code, hour, minute, value):
        return EastmoneySectorFundFlowSnapshot.objects.create(
            sector_code=code,
            sector_name=f"板块{code}",
            trade_date=self.trade_date,
            snapshot_time=self.local_datetime(hour, minute),
            main_net_inflow=value,
        )

    def test_axis_contains_every_elapsed_standard_tick(self):
        axis = get_trading_time_axis(self.trade_date, now=self.local_datetime(10, 5))
        self.assertEqual(
            [timezone.localtime(slot).strftime("%H:%M") for slot in axis],
            ["09:30", "09:45", "10:00"],
        )

    def test_current_trade_day_cache_expires_at_the_next_trading_tick(self):
        self.assertEqual(
            get_sector_intraday_cache_timeout(
                self.trade_date,
                now=self.local_datetime(10, 17),
            ),
            13 * 60,
        )

    def test_aggregation_reuses_cache_before_the_next_trading_tick(self):
        self.create_snapshot("BK0001", 9, 30, 100_000_000)

        with patch(
            "fundflow.services.trading_time.timezone.now",
            return_value=self.local_datetime(10, 17),
        ):
            first_payload = aggregate_sector_intraday(self.trade_date, inflow_top=1, outflow_top=0)

        with (
            patch(
                "fundflow.services.trading_time.timezone.now",
                return_value=self.local_datetime(10, 29),
            ),
            self.assertNumQueries(0),
        ):
            cached_payload = aggregate_sector_intraday(self.trade_date, inflow_top=1, outflow_top=0)

        self.assertEqual(cached_payload, first_payload)

        with (
            patch(
                "fundflow.services.trading_time.timezone.now",
                return_value=self.local_datetime(10, 30),
            ),
            self.assertNumQueries(1),
        ):
            aggregate_sector_intraday(self.trade_date, inflow_top=1, outflow_top=0)

    def test_aggregation_uses_direct_snapshots_and_forward_fills_missing_ticks(self):
        self.create_snapshot("BK0001", 9, 30, 100_000_000)
        self.create_snapshot("BK0001", 10, 0, 300_000_000)

        with patch(
            "fundflow.services.trading_time.timezone.now",
            return_value=self.local_datetime(10, 5),
        ):
            payload = aggregate_sector_intraday(self.trade_date, inflow_top=1, outflow_top=0)

        self.assertEqual(payload["time_points"], ["09:30", "09:45", "10:00"])
        self.assertEqual(payload["series"][0]["code"], "BK0001")
        self.assertEqual(payload["series"][0]["data"], [1.0, 1.0, 3.0])
        self.assertTrue(payload["stale"])

    def test_historical_date_uses_full_time_axis(self):
        historical_date = date(2026, 8, 18)
        EastmoneySectorFundFlowSnapshot.objects.create(
            sector_code="BK0001",
            sector_name="测试板块",
            trade_date=historical_date,
            snapshot_time=timezone.make_aware(datetime(2026, 8, 18, 9, 30)),
            main_net_inflow=100_000_000,
        )

        payload = aggregate_sector_intraday(historical_date, inflow_top=1, outflow_top=0)

        self.assertEqual(len(payload["time_points"]), 18)
        self.assertEqual(payload["time_points"][0], "09:30")
        self.assertEqual(payload["time_points"][-1], "15:00")

    def test_selects_inflow_and_outflow_leaders_independently(self):
        selected = select_sector_series(
            [
                {"code": "p10", "latest_net_inflow": 10},
                {"code": "p8", "latest_net_inflow": 8},
                {"code": "zero", "latest_net_inflow": 0},
                {"code": "n5", "latest_net_inflow": -5},
                {"code": "n7", "latest_net_inflow": -7},
            ],
            inflow_top=2,
            outflow_top=2,
        )
        self.assertEqual([item["code"] for item in selected], ["p10", "p8", "n7", "n5"])


class SectorSnapshotCommandTests(TestCase):
    @staticmethod
    def cleaned_row(timestamp=None):
        row = {
            "sector_code": "BK0420",
            "sector_name": "航空机场",
            "latest_index": 1000,
            "change_pct": 1,
            "main_net_inflow": 100,
            "main_net_inflow_ratio": 2,
            "super_large_net_inflow": 10,
            "large_net_inflow": 20,
            "medium_net_inflow": 30,
            "small_net_inflow": 40,
        }
        if timestamp is not None:
            row["source_timestamp"] = timestamp
        return row

    def test_command_stores_snapshot_at_floored_tick(self):
        now = timezone.make_aware(datetime(2026, 8, 19, 10, 10))
        with (
            patch(
                "fundflow.management.commands.fetch_sector_fund_flow.timezone.now",
                return_value=now,
            ),
            patch(
                "fundflow.management.commands.fetch_sector_fund_flow."
                "EastmoneyClient.fetch_all_sector_fund_flow",
                return_value=[self.cleaned_row()],
            ),
        ):
            call_command("fetch_sector_fund_flow")

        snapshot = EastmoneySectorFundFlowSnapshot.objects.get(sector_code="BK0420")
        self.assertEqual(timezone.localtime(snapshot.snapshot_time).strftime("%H:%M"), "10:00")

    def test_command_does_not_accept_removed_force_option(self):
        parser = Command().create_parser("manage.py", "fetch_sector_fund_flow")
        with self.assertRaises(CommandError):
            parser.parse_args(["--force"])

    def test_latest_option_uses_upstream_time_and_aligns_to_last_legal_tick(self):
        now = timezone.make_aware(datetime(2026, 8, 26, 15, 56))
        upstream_time = timezone.make_aware(datetime(2026, 8, 26, 15, 30))
        with (
            patch(
                "fundflow.management.commands.fetch_sector_fund_flow.timezone.now",
                return_value=now,
            ),
            patch(
                "fundflow.management.commands.fetch_sector_fund_flow."
                "EastmoneyClient.fetch_all_sector_fund_flow",
                return_value=[self.cleaned_row(int(upstream_time.timestamp()))],
            ),
        ):
            call_command("fetch_sector_fund_flow", "--latest")

        snapshot = EastmoneySectorFundFlowSnapshot.objects.get(sector_code="BK0420")
        self.assertEqual(snapshot.trade_date, date(2026, 8, 26))
        self.assertEqual(timezone.localtime(snapshot.snapshot_time).strftime("%H:%M"), "15:00")

    def test_command_skips_non_trading_time_and_statutory_holiday(self):
        for now in [
            timezone.make_aware(datetime(2026, 8, 19, 15, 30)),
            timezone.make_aware(datetime(2026, 1, 1, 10, 0)),
        ]:
            with (
                patch(
                    "fundflow.management.commands.fetch_sector_fund_flow.timezone.now",
                    return_value=now,
                ),
                patch(
                    "fundflow.management.commands.fetch_sector_fund_flow."
                    "EastmoneyClient.fetch_all_sector_fund_flow"
                ) as fetch,
            ):
                call_command("fetch_sector_fund_flow")
            fetch.assert_not_called()

        self.assertFalse(EastmoneySectorFundFlowSnapshot.objects.exists())


class SectorApiTests(TestCase):
    def test_only_sector_routes_are_exposed(self):
        self.assertEqual(
            {pattern.name for pattern in urlpatterns},
            {"sector-list", "sector-intraday"},
        )

    def test_intraday_api_defaults_to_five_per_direction(self):
        request = APIRequestFactory().get("/api/sectors/intraday/", {"date": "2026-08-19"})
        with patch(
            "fundflow.views.aggregate_sector_intraday",
            return_value={"trade_date": "2026-08-19", "time_points": [], "series": [], "stale": True},
        ) as aggregate:
            response = SectorIntradayView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        aggregate.assert_called_once_with(
            trade_date=date(2026, 8, 19),
            inflow_top=5,
            outflow_top=5,
        )

    def test_intraday_api_allows_twenty_five_per_direction(self):
        request = APIRequestFactory().get(
            "/api/sectors/intraday/",
            {"date": "2026-08-19", "inflow_top": "25", "outflow_top": "25"},
        )
        with patch(
            "fundflow.views.aggregate_sector_intraday",
            return_value={"time_points": [], "series": []},
        ) as aggregate:
            SectorIntradayView.as_view()(request)

        aggregate.assert_called_once_with(
            trade_date=date(2026, 8, 19),
            inflow_top=25,
            outflow_top=25,
        )

    def test_intraday_api_clamps_requested_limits(self):
        request = APIRequestFactory().get(
            "/api/sectors/intraday/",
            {"date": "2026-08-19", "inflow_top": "100", "outflow_top": "-2"},
        )
        with patch(
            "fundflow.views.aggregate_sector_intraday",
            return_value={"time_points": [], "series": []},
        ) as aggregate:
            SectorIntradayView.as_view()(request)

        aggregate.assert_called_once_with(
            trade_date=date(2026, 8, 19),
            inflow_top=30,
            outflow_top=0,
        )

    def test_sector_list_uses_the_latest_snapshot_for_the_selected_date(self):
        trade_date = date(2026, 8, 19)
        EastmoneySectorFundFlowSnapshot.objects.create(
            sector_code="BK0001",
            sector_name="早盘板块",
            trade_date=trade_date,
            snapshot_time=timezone.make_aware(datetime(2026, 8, 19, 9, 30)),
            main_net_inflow=1,
        )
        EastmoneySectorFundFlowSnapshot.objects.create(
            sector_code="BK0002",
            sector_name="午后板块",
            trade_date=trade_date,
            snapshot_time=timezone.make_aware(datetime(2026, 8, 19, 13, 0)),
            main_net_inflow=1,
        )

        response = SectorListView.as_view()(APIRequestFactory().get("/api/sectors/"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [{"code": "BK0002", "name": "午后板块"}])
