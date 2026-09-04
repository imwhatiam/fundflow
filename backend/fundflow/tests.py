from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, call, patch

import requests
from django.conf import settings
from django.core.cache import cache, caches
from django.core.cache.backends.filebased import FileBasedCache
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from fundflow.management.commands.fetch_sector_fund_flow import Command
from fundflow.models import (
    EastmoneySectorFundFlowSnapshot,
    EastmoneySectorFundFlowSnapshotStatus,
)
from fundflow.services.aggregation import (
    aggregate_sector_intraday,
    get_sector_intraday_cache_timeout,
    get_trading_time_axis,
    select_sector_series,
)
from fundflow.services.eastmoney.constants import (
    EASTMONEY_SECTOR_CLIST_UT,
    EASTMONEY_SECTOR_FS,
    EASTMONEY_RANKING_LIMIT,
    HEADERS,
    MAX_REQUEST_INTERVAL_TOTAL_SECONDS,
    MAX_RETRIES,
    MAX_FETCH_DURATION_SECONDS,
    MIN_RETRY_INTERVAL_SECONDS,
    SECTOR_FIELDS,
    SUCCESSFUL_RANKING_INTERVAL_SECONDS,
)
from fundflow.services.eastmoney.http_client import EastmoneyHttpClient
from fundflow.services.eastmoney.parser import parse_sector_row
from fundflow.services.eastmoney.ranking_fetcher import SectorRankingFetcher
from fundflow.services.eastmoney.request_schedule import prepare_interval_plan
from fundflow.services.eastmoney.types import RequestIntervalPlan, SectorFundFlowFetchResult
from fundflow.services.trading_calendar import (
    is_a_share_trading_day,
    previous_a_share_trading_day,
    trading_day_window,
)
from fundflow.services.sector_intraday_builders import (
    build_period_rankings,
    build_sector_intraday_payload,
)
from fundflow.services.sector_intraday_cache import sector_intraday_cache_key
from fundflow.services.sector_intraday_service import query_sector_intraday_history
from fundflow.services.trading_time import floor_to_15min, trading_slots_for_day
from fundflow.urls import urlpatterns
from fundflow.views import SectorIntradayHistoryView, SectorIntradayView, SectorListView


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


class CacheConfigurationTests(SimpleTestCase):
    def test_development_uses_a_shared_file_based_cache(self):
        self.assertEqual(
            settings.CACHES["default"]["BACKEND"],
            "django.core.cache.backends.filebased.FileBasedCache",
        )
        self.assertEqual(
            Path(settings.CACHES["default"]["LOCATION"]),
            settings.BASE_DIR / ".cache" / "django",
        )
        self.assertIsInstance(caches["default"], FileBasedCache)


class TradingCalendarTests(SimpleTestCase):
    def test_statutory_holiday_and_weekend_makeup_workday_are_not_trading_days(self):
        self.assertFalse(is_a_share_trading_day(date(2026, 1, 1)))
        # 调休周日即使被标记为工作日，A 股仍不开市。
        self.assertFalse(is_a_share_trading_day(date(2026, 1, 4)))

    def test_previous_trading_day_skips_holiday_and_weekend(self):
        self.assertEqual(previous_a_share_trading_day(date(2026, 1, 1)), date(2025, 12, 31))

    def test_trading_day_window_backfills_from_a_non_trading_end_date(self):
        self.assertEqual(
            trading_day_window(date(2026, 1, 1), count=3),
            [date(2025, 12, 31), date(2025, 12, 30), date(2025, 12, 29)],
        )


class EastmoneySectorClientTests(SimpleTestCase):
    @staticmethod
    def interval_plan():
        return RequestIntervalPlan(
            retry_delays=tuple(range(45, 45 + MAX_RETRIES * 2)),
            successful_ranking_delay=SUCCESSFUL_RANKING_INTERVAL_SECONDS,
        )

    def fetcher(self, http_client, *, plan=None, sleep=None, clock=None):
        return SectorRankingFetcher(
            http_client=http_client,
            interval_plan_factory=lambda: plan or self.interval_plan(),
            sleep=sleep or Mock(),
            clock=clock or Mock(return_value=0),
        )

    def test_requests_only_third_level_industry_inflow_and_outflow_top_fifty_rankings(self):
        http_client = Mock()
        http_client.get_json.side_effect = [
            {"data": {"diff": [sector_row("BK0001", 100)]}},
            {"data": {"diff": [sector_row("BK0002", -100)]}},
        ]
        fetcher = self.fetcher(http_client)

        result = fetcher.fetch_sector_fund_flow_leaders()

        self.assertTrue(result.inflow_succeeded)
        self.assertTrue(result.outflow_succeeded)
        self.assertEqual([item["sector_code"] for item in result.rows], ["BK0001", "BK0002"])
        self.assertEqual(EASTMONEY_SECTOR_CLIST_UT, "8dec03ba335b81bf4ebdf7b29ec27d15")
        self.assertEqual(EASTMONEY_SECTOR_FS, "m:90+s:8+f:!50")
        self.assertEqual(EASTMONEY_RANKING_LIMIT, 50)
        self.assertEqual(HEADERS["Referer"], "https://data.eastmoney.com/bkzj/hy.html")
        params = [call.args[0] for call in http_client.get_json.call_args_list]
        self.assertEqual([item["po"] for item in params], [1, 0])
        self.assertEqual([item["pn"] for item in params], [1, 1])
        self.assertEqual([item["pz"] for item in params], [50, 50])
        self.assertTrue(all(item["ut"] == EASTMONEY_SECTOR_CLIST_UT for item in params))
        self.assertTrue(all(item["fs"] == EASTMONEY_SECTOR_FS for item in params))
        self.assertTrue(all(item["fields"] == SECTOR_FIELDS for item in params))
        self.assertTrue(all(item["fid"] == "f62" for item in params))
        self.assertTrue(all("fid0" not in item for item in params))

    def test_interval_plan_is_precomputed_within_the_seven_hundred_second_budget(self):
        random_source = Mock()
        random_source.sample.return_value = list(range(45, 55))

        plan = prepare_interval_plan(random_source=random_source)

        self.assertEqual(len(plan.retry_delays), MAX_RETRIES * 2)
        self.assertTrue(all(delay >= MIN_RETRY_INTERVAL_SECONDS for delay in plan.retry_delays))
        self.assertEqual(len(set(plan.retry_delays)), MAX_RETRIES * 2)
        self.assertEqual(plan.successful_ranking_delay, SUCCESSFUL_RANKING_INTERVAL_SECONDS)
        self.assertNotIn(plan.successful_ranking_delay, plan.retry_delays)
        self.assertEqual(plan.total_seconds, 615)
        self.assertLessEqual(plan.total_seconds, MAX_REQUEST_INTERVAL_TOTAL_SECONDS)
        random_source.sample.assert_called_once_with(range(45, 55), MAX_RETRIES * 2)

    def test_successful_first_ranking_waits_exactly_one_hundred_twenty_seconds_before_outflow(self):
        http_client = Mock()
        http_client.get_json.side_effect = [
            {"data": {"diff": [sector_row("BK0001", 100)]}},
            {"data": {"diff": [sector_row("BK0002", -100)]}},
        ]
        sleep = Mock()
        fetcher = self.fetcher(http_client, sleep=sleep)

        fetcher.fetch_sector_fund_flow_leaders()

        self.assertEqual(sleep.call_args_list, [((SUCCESSFUL_RANKING_INTERVAL_SECONDS,), {})])

    def test_empty_first_response_is_still_a_successful_request_and_waits_one_hundred_twenty_seconds(self):
        http_client = Mock()
        http_client.get_json.side_effect = [
            {"data": {"diff": []}},
            {"data": {"diff": [sector_row("BK0002", -100)]}},
        ]
        sleep = Mock()
        fetcher = self.fetcher(http_client, sleep=sleep)

        result = fetcher.fetch_sector_fund_flow_leaders()

        self.assertFalse(result.inflow_succeeded)
        self.assertTrue(result.outflow_succeeded)
        self.assertEqual(sleep.call_args_list, [((SUCCESSFUL_RANKING_INTERVAL_SECONDS,), {})])

    def test_each_failed_ranking_is_retried_five_times_with_precomputed_delays(self):
        http_client = Mock()
        success_response = {"data": {"diff": []}}
        http_client.get_json.side_effect = [requests.RequestException("temporary")] * MAX_RETRIES + [success_response]
        sleep = Mock()
        retry_delays = (47, 49, 51, 53, 55, 56, 57, 58, 59, 60)
        plan = RequestIntervalPlan(retry_delays, SUCCESSFUL_RANKING_INTERVAL_SECONDS)
        fetcher = self.fetcher(http_client, plan=plan, sleep=sleep)

        result = fetcher._fetch_ranking_with_retry({"pn": 1}, retry_delays=iter(retry_delays), deadline=100)

        self.assertEqual(result, success_response)
        self.assertEqual(http_client.get_json.call_count, MAX_RETRIES + 1)
        self.assertEqual(sleep.call_args_list, [((delay,), {}) for delay in retry_delays[:MAX_RETRIES]])

    def test_all_failed_requests_consume_only_retry_intervals_and_stay_below_hard_limit(self):
        http_client = Mock()
        http_client.get_json.side_effect = requests.RequestException("unavailable")
        sleep = Mock()
        fetcher = self.fetcher(http_client, sleep=sleep)

        result = fetcher.fetch_sector_fund_flow_leaders()

        self.assertFalse(result.inflow_succeeded)
        self.assertFalse(result.outflow_succeeded)
        self.assertEqual(http_client.get_json.call_count, (MAX_RETRIES + 1) * 2)
        sleep_delays = [call.args[0] for call in sleep.call_args_list]
        self.assertEqual(len(sleep_delays), MAX_RETRIES * 2)
        self.assertTrue(all(delay >= MIN_RETRY_INTERVAL_SECONDS for delay in sleep_delays))
        self.assertEqual(len(set(sleep_delays)), len(sleep_delays))
        self.assertLessEqual(sum(sleep_delays), MAX_REQUEST_INTERVAL_TOTAL_SECONDS)
        self.assertLess(MAX_FETCH_DURATION_SECONDS, 890)

    def test_deadline_stops_a_retry_instead_of_shortening_the_required_interval(self):
        http_client = Mock()
        http_client.get_json.side_effect = requests.RequestException("temporary")
        sleep = Mock()
        clock = Mock(side_effect=[56, 56])
        fetcher = self.fetcher(http_client, sleep=sleep, clock=clock)

        result = fetcher._fetch_ranking_with_retry(
            {"pn": 1}, retry_delays=iter((MIN_RETRY_INTERVAL_SECONDS,)), deadline=100
        )

        self.assertIsNone(result)
        self.assertEqual(http_client.get_json.call_count, 1)
        sleep.assert_not_called()

    def test_later_outflow_response_overwrites_a_duplicate_code(self):
        http_client = Mock()
        newer_row = sector_row("BK0001", -200)
        newer_row["f14"] = "更新后的板块名称"
        http_client.get_json.side_effect = [
            {"data": {"diff": [sector_row("BK0001", 100), sector_row("BK0002", 80)]}},
            {"data": {"diff": [newer_row, sector_row("BK0003", -300)]}},
        ]
        result = self.fetcher(http_client).fetch_sector_fund_flow_leaders()

        result_by_code = {item["sector_code"]: item for item in result.rows}
        self.assertEqual(set(result_by_code), {"BK0001", "BK0002", "BK0003"})
        self.assertEqual(result_by_code["BK0001"]["main_net_inflow"], -200)
        self.assertEqual(result_by_code["BK0001"]["sector_name"], "更新后的板块名称")

    def test_one_failed_ranking_keeps_the_other_direction(self):
        http_client = Mock()
        http_client.get_json.side_effect = [
            {"data": {"diff": [sector_row("BK0001", 100)]}},
            *[requests.RequestException("unavailable") for _ in range(MAX_RETRIES + 1)],
        ]
        fetcher = self.fetcher(http_client)

        with self.assertLogs("fundflow.services.eastmoney.ranking_fetcher", level="WARNING") as logs:
            result = fetcher.fetch_sector_fund_flow_leaders()

        self.assertTrue(result.inflow_succeeded)
        self.assertFalse(result.outflow_succeeded)
        self.assertEqual([item["sector_code"] for item in result.rows], ["BK0001"])
        self.assertIn("继续处理另一方向", "\n".join(logs.output))

    def test_empty_successful_response_marks_that_direction_incomplete(self):
        http_client = Mock()
        http_client.get_json.side_effect = [
            {"data": {"diff": [sector_row("BK0001", 100)]}},
            {"data": {"diff": []}},
        ]
        result = self.fetcher(http_client).fetch_sector_fund_flow_leaders()

        self.assertTrue(result.inflow_succeeded)
        self.assertFalse(result.outflow_succeeded)
        self.assertEqual([item["sector_code"] for item in result.rows], ["BK0001"])

    def test_parser_preserves_upstream_snapshot_timestamp(self):
        self.assertEqual(
            parse_sector_row(sector_row("BK0001", timestamp=1_777_000_000)),
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
        success_response.json.return_value = {"data": {"diff": []}}
        success_session = Mock()
        success_session.get.return_value = success_response
        http_client = EastmoneyHttpClient()
        fetcher = self.fetcher(http_client, sleep=Mock())

        with patch(
            "fundflow.services.eastmoney.http_client.requests.Session",
            side_effect=[failed_session, success_session],
        ):
            self.assertEqual(
                fetcher._fetch_ranking_with_retry({"pn": 1}, retry_delays=iter((45,)), deadline=100),
                {"data": {"diff": []}},
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

    def create_snapshot_status(self, hour, minute, *, inflow_succeeded, outflow_succeeded):
        return EastmoneySectorFundFlowSnapshotStatus.objects.create(
            trade_date=self.trade_date,
            snapshot_time=self.local_datetime(hour, minute),
            inflow_succeeded=inflow_succeeded,
            outflow_succeeded=outflow_succeeded,
        )

    def test_aggregation_uses_previous_tick_for_a_missing_direction(self):
        self.create_snapshot("BK_IN_OLD", 9, 30, 100_000_000)
        self.create_snapshot("BK_OUT_OLD", 9, 30, -200_000_000)
        self.create_snapshot("BK_IN_NEW", 9, 45, 300_000_000)
        # 模拟同一刻度先前部分写入留下的流出数据；状态失败时不能把它当成最新榜单。
        self.create_snapshot("BK_OUT_RETAINED", 9, 45, -900_000_000)
        self.create_snapshot_status(9, 45, inflow_succeeded=True, outflow_succeeded=False)

        with patch(
            "fundflow.services.trading_time.timezone.now",
            return_value=self.local_datetime(9, 50),
        ):
            payload = aggregate_sector_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        by_code = {item["code"]: item for item in payload["series"]}
        self.assertEqual(set(by_code), {"BK_IN_NEW", "BK_OUT_OLD"})
        self.assertEqual(by_code["BK_IN_NEW"]["data"], [0.0, 3.0])
        self.assertEqual(by_code["BK_OUT_OLD"]["data"], [-2.0, -2.0])
        self.assertTrue(payload["stale"])

    def test_fallback_outflow_can_use_a_sector_outside_the_displayed_inflow_top(self):
        self.create_snapshot("BK_SHARED", 9, 30, -300_000_000)
        self.create_snapshot("BK_OUT_OTHER", 9, 30, -100_000_000)
        self.create_snapshot("BK_IN_TOP", 9, 45, 500_000_000)
        self.create_snapshot("BK_SHARED", 9, 45, 200_000_000)
        self.create_snapshot_status(9, 45, inflow_succeeded=True, outflow_succeeded=False)

        with patch(
            "fundflow.services.trading_time.timezone.now",
            return_value=self.local_datetime(9, 50),
        ):
            payload = aggregate_sector_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        self.assertEqual([item["code"] for item in payload["series"]], ["BK_IN_TOP", "BK_SHARED"])
        self.assertEqual(payload["series"][1]["data"], [-3.0, -3.0])

    def test_missing_direction_without_a_previous_tick_marks_payload_stale(self):
        self.create_snapshot("BK_IN", 9, 30, 100_000_000)
        self.create_snapshot_status(9, 30, inflow_succeeded=True, outflow_succeeded=True)

        with patch(
            "fundflow.services.trading_time.timezone.now",
            return_value=self.local_datetime(9, 35),
        ):
            payload = aggregate_sector_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        self.assertEqual([item["code"] for item in payload["series"]], ["BK_IN"])
        self.assertTrue(payload["stale"])

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
            self.assertNumQueries(2),
        ):
            aggregate_sector_intraday(self.trade_date, inflow_top=1, outflow_top=0)

    def test_only_latest_snapshot_codes_can_enter_the_current_ranking(self):
        self.create_snapshot("BK_OLD", 9, 30, 900_000_000)
        self.create_snapshot("BK_NEW", 10, 0, 100_000_000)

        with patch(
            "fundflow.services.trading_time.timezone.now",
            return_value=self.local_datetime(10, 5),
        ):
            payload = aggregate_sector_intraday(self.trade_date, inflow_top=2, outflow_top=0)

        self.assertEqual([item["code"] for item in payload["series"]], ["BK_NEW"])
        self.assertEqual(payload["series"][0]["data"], [0.0, 0.0, 1.0])

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


class SectorHistoryServiceTests(TestCase):
    def create_snapshot(self, trade_date, hour, minute, code, value):
        return EastmoneySectorFundFlowSnapshot.objects.create(
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
                "stale": False,
            },
            {
                "trade_date": "2026-09-02",
                "time_points": [],
                "series": [],
                "stale": True,
            },
            {
                "trade_date": "2026-09-01",
                "time_points": ["09:30", "15:00"],
                "series": [
                    {"code": "A", "name": "板块A", "latest_net_inflow": -3.0, "data": [-1.0, -3.0]},
                    {"code": "B", "name": "板块B", "latest_net_inflow": 2.0, "data": [1.0, 2.0]},
                    {"code": "C", "name": "板块C", "latest_net_inflow": -4.0, "data": [-2.0, -4.0]},
                ],
                "stale": False,
            },
        ]

        with patch(
            "fundflow.services.sector_intraday_service.query_sector_intraday",
            side_effect=daily_payloads,
        ) as query_intraday:
            payload = query_sector_intraday_history(
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
                    "stale": False,
                },
                {
                    "trade_date": "2026-09-02",
                    "time_points": ["15:00"],
                    "series": [],
                    "stale": True,
                },
                {
                    "trade_date": "2026-09-01",
                    "time_points": ["15:00"],
                    "series": [
                        {"code": "A", "name": "板块A", "latest_net_inflow": -3.0, "data": [-3.0]},
                        {"code": "B", "name": "板块B", "latest_net_inflow": 2.0, "data": [2.0]},
                        {"code": "C", "name": "板块C", "latest_net_inflow": -4.0, "data": [-4.0]},
                    ],
                    "stale": False,
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
        payload = build_sector_intraday_payload(
            trade_date=date(2026, 9, 3),
            time_axis=time_axis,
            snapshot_rows=[
                {"sector_code": "A", "sector_name": "A", "snapshot_time": time_axis[1], "main_net_inflow": 100_000_000},
                {"sector_code": "B", "sector_name": "B", "snapshot_time": time_axis[0], "main_net_inflow": -200_000_000},
            ],
            status_rows=[{"snapshot_time": time_axis[1], "inflow_succeeded": True, "outflow_succeeded": True}],
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
            sector_intraday_cache_key(**common, additional_codes=("A",)),
            sector_intraday_cache_key(**common, additional_codes=("B",)),
        )


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
                "EastmoneyClient.fetch_sector_fund_flow_leaders",
                return_value=SectorFundFlowFetchResult([self.cleaned_row()], True, True),
            ),
        ):
            call_command("fetch_sector_fund_flow")

        snapshot = EastmoneySectorFundFlowSnapshot.objects.get(sector_code="BK0420")
        self.assertEqual(timezone.localtime(snapshot.snapshot_time).strftime("%H:%M"), "10:00")

    def test_leader_fetch_keeps_records_that_are_not_currently_ranked(self):
        now = timezone.make_aware(datetime(2026, 8, 19, 10, 10))
        snapshot_time = timezone.make_aware(datetime(2026, 8, 19, 10, 0))
        EastmoneySectorFundFlowSnapshot.objects.create(
            sector_code="BK9999",
            sector_name="未进入当前 Top 50 的已有板块",
            trade_date=date(2026, 8, 19),
            snapshot_time=snapshot_time,
            main_net_inflow=999,
        )
        client = Mock()
        client.fetch_sector_fund_flow_leaders.return_value = SectorFundFlowFetchResult(
            [self.cleaned_row()], True, True
        )

        with (
            patch(
                "fundflow.management.commands.fetch_sector_fund_flow.timezone.now",
                return_value=now,
            ),
            patch(
                "fundflow.management.commands.fetch_sector_fund_flow.EastmoneyClient",
                return_value=client,
            ),
        ):
            call_command("fetch_sector_fund_flow")

        self.assertTrue(
            EastmoneySectorFundFlowSnapshot.objects.filter(
                sector_code="BK9999", snapshot_time=snapshot_time
            ).exists()
        )
        self.assertTrue(
            EastmoneySectorFundFlowSnapshot.objects.filter(
                sector_code="BK0420", snapshot_time=snapshot_time
            ).exists()
        )

    def test_command_records_partial_fetch_status(self):
        now = timezone.make_aware(datetime(2026, 8, 19, 10, 10))
        result = SectorFundFlowFetchResult([self.cleaned_row()], True, False)
        with (
            patch(
                "fundflow.management.commands.fetch_sector_fund_flow.timezone.now",
                return_value=now,
            ),
            patch(
                "fundflow.management.commands.fetch_sector_fund_flow."
                "EastmoneyClient.fetch_sector_fund_flow_leaders",
                return_value=result,
            ),
        ):
            call_command("fetch_sector_fund_flow")

        status = EastmoneySectorFundFlowSnapshotStatus.objects.get()
        self.assertTrue(status.inflow_succeeded)
        self.assertFalse(status.outflow_succeeded)

    def test_command_upserts_rows_when_the_same_tick_is_fetched_again(self):
        now = timezone.make_aware(datetime(2026, 8, 19, 10, 10))
        snapshot_time = timezone.make_aware(datetime(2026, 8, 19, 10, 0))
        EastmoneySectorFundFlowSnapshot.objects.create(
            sector_code="BK0420",
            sector_name="旧名称",
            trade_date=date(2026, 8, 19),
            snapshot_time=snapshot_time,
            main_net_inflow=1,
        )
        updated_row = self.cleaned_row()
        updated_row["main_net_inflow"] = 999
        updated_row["sector_name"] = "新名称"
        with (
            patch(
                "fundflow.management.commands.fetch_sector_fund_flow.timezone.now",
                return_value=now,
            ),
            patch(
                "fundflow.management.commands.fetch_sector_fund_flow."
                "EastmoneyClient.fetch_sector_fund_flow_leaders",
                return_value=SectorFundFlowFetchResult([updated_row], True, True),
            ),
        ):
            call_command("fetch_sector_fund_flow")

        snapshot = EastmoneySectorFundFlowSnapshot.objects.get(
            sector_code="BK0420", snapshot_time=snapshot_time
        )
        self.assertEqual(snapshot.sector_name, "新名称")
        self.assertEqual(snapshot.main_net_inflow, 999)

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
                "EastmoneyClient.fetch_sector_fund_flow_leaders",
                return_value=SectorFundFlowFetchResult([self.cleaned_row(int(upstream_time.timestamp()))], True, True),
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
                    "EastmoneyClient.fetch_sector_fund_flow_leaders"
                ) as fetch,
            ):
                call_command("fetch_sector_fund_flow")
            fetch.assert_not_called()

        self.assertFalse(EastmoneySectorFundFlowSnapshot.objects.exists())


class SectorApiTests(TestCase):
    def test_only_sector_routes_are_exposed(self):
        self.assertEqual(
            {pattern.name for pattern in urlpatterns},
            {"sector-list", "sector-intraday", "sector-intraday-history"},
        )

    def test_intraday_api_defaults_to_five_per_direction(self):
        request = APIRequestFactory().get("/eastmoney-api/sectors/intraday/", {"date": "2026-08-19"})
        with patch(
            "fundflow.views.query_sector_intraday",
            return_value={"trade_date": "2026-08-19", "time_points": [], "series": [], "stale": True},
        ) as query_intraday:
            response = SectorIntradayView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        query_intraday.assert_called_once_with(
            trade_date=date(2026, 8, 19),
            inflow_top=5,
            outflow_top=5,
        )

    def test_intraday_api_allows_twenty_five_per_direction(self):
        request = APIRequestFactory().get(
            "/eastmoney-api/sectors/intraday/",
            {"date": "2026-08-19", "inflow_top": "25", "outflow_top": "25"},
        )
        with patch(
            "fundflow.views.query_sector_intraday",
            return_value={"time_points": [], "series": []},
        ) as query_intraday:
            SectorIntradayView.as_view()(request)

        query_intraday.assert_called_once_with(
            trade_date=date(2026, 8, 19),
            inflow_top=25,
            outflow_top=25,
        )

    def test_intraday_api_clamps_requested_limits(self):
        request = APIRequestFactory().get(
            "/eastmoney-api/sectors/intraday/",
            {"date": "2026-08-19", "inflow_top": "100", "outflow_top": "-2"},
        )
        with patch(
            "fundflow.views.query_sector_intraday",
            return_value={"time_points": [], "series": []},
        ) as query_intraday:
            SectorIntradayView.as_view()(request)

        query_intraday.assert_called_once_with(
            trade_date=date(2026, 8, 19),
            inflow_top=30,
            outflow_top=0,
        )

    def test_intraday_history_api_delegates_a_requested_trading_day_window(self):
        request = APIRequestFactory().get(
            "/eastmoney-api/sectors/intraday/history/",
            {"date": "2026-08-19", "days": "5", "inflow_top": "25", "outflow_top": "25"},
        )
        payload = {
            "end_date": "2026-08-19",
            "items": [{"trade_date": "2026-08-19", "time_points": [], "series": [], "stale": False}],
        }
        with patch("fundflow.views.query_sector_intraday_history", return_value=payload) as query_history:
            response = SectorIntradayHistoryView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, payload)
        query_history.assert_called_once_with(
            end_date=date(2026, 8, 19),
            days=5,
            inflow_top=25,
            outflow_top=25,
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

        response = SectorListView.as_view()(APIRequestFactory().get("/eastmoney-api/sectors/"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [{"code": "BK0002", "name": "午后板块"}])
