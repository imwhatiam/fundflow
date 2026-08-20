from datetime import date, datetime
import threading
from unittest.mock import Mock, call, patch

import requests
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from fundflow.models import Sector, SectorConstituent, StockFundFlowSnapshot
from fundflow.services.aggregation import (
    aggregate_sector_intraday,
    get_trading_time_axis,
    select_sector_series,
)
from fundflow.services.backfill import _downsample_to_15min, is_already_backfilled
from fundflow.services.eastmoney_client import EastmoneyClient
from fundflow.services.trading_time import (
    floor_to_15min,
    trading_slots_for_day,
    trading_slots_until,
)
from fundflow.views import SectorIntradayView


class EastmoneyClientRequestTests(SimpleTestCase):
    def test_stock_fund_flow_defaults_to_two_hundred_rows_per_page(self):
        client = EastmoneyClient()

        with patch.object(
            client,
            "_get_with_retry",
            return_value={"data": {"total": 0, "diff": []}},
        ) as get_with_retry:
            client.fetch_all_stock_fund_flow()

        self.assertEqual(get_with_retry.call_args.args[0]["pz"], 200)

    def test_stock_fund_flow_request_matches_current_detail_page(self):
        client = EastmoneyClient(page_size=50)

        with patch.object(
            client,
            "_get_with_retry",
            return_value={"data": {"diff": []}},
        ) as get_with_retry:
            client.fetch_all_stock_fund_flow()

        params = get_with_retry.call_args.args[0]
        self.assertEqual(params["ut"], "8dec03ba335b81bf4ebdf7b29ec27d15")
        self.assertEqual(params["fid"], "f12")
        self.assertEqual(params["pz"], 50)
        self.assertEqual(
            params["fields"],
            "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,"
            "f84,f87,f204,f205,f124,f1,f13",
        )

    def test_stock_fund_flow_fetches_every_page(self):
        client = EastmoneyClient(page_size=2, page_delay=0.25)
        responses = [
            {
                "data": {
                    "total": 3,
                    "diff": [
                        {"f12": "000001", "f13": 0, "f14": "平安银行", "f62": 1},
                        {"f12": "600000", "f13": 1, "f14": "浦发银行", "f62": 2},
                    ],
                }
            },
            {
                "data": {
                    "total": 3,
                    "diff": [
                        {"f12": "430047", "f13": 2, "f14": "诺思兰德", "f62": 3},
                    ],
                }
            },
        ]

        with (
            patch.object(
                client, "_get_with_retry", side_effect=responses
            ) as get_with_retry,
            patch("fundflow.services.eastmoney_client.time.sleep") as sleep,
        ):
            results = client.fetch_all_stock_fund_flow()

        self.assertEqual(
            [row["stock_code"] for row in results],
            ["000001", "600000", "430047"],
        )
        self.assertEqual(
            [
                request_call.args[0]["pn"]
                for request_call in get_with_retry.call_args_list
            ],
            [1, 2],
        )
        sleep.assert_called_once_with(0.25)

    def test_uses_actual_row_count_when_response_is_smaller_than_page_size(self):
        client = EastmoneyClient(page_size=200, page_delay=0)
        responses = [
            {
                "data": {
                    "total": 3,
                    "diff": [
                        {"f12": "000001", "f13": 0, "f14": "股票1", "f62": 1},
                    ],
                }
            },
            {
                "data": {
                    "total": 3,
                    "diff": [
                        {"f12": "000002", "f13": 0, "f14": "股票2", "f62": 2},
                    ],
                }
            },
            {
                "data": {
                    "total": 3,
                    "diff": [
                        {"f12": "000003", "f13": 0, "f14": "股票3", "f62": 3},
                    ],
                }
            },
        ]

        with patch.object(client, "_get_with_retry", side_effect=responses) as request:
            results = client.fetch_all_stock_fund_flow()

        self.assertEqual(len(results), 3)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(
            [item.args[0]["pn"] for item in request.call_args_list],
            [1, 2, 3],
        )

    def test_without_total_keeps_fetching_until_an_empty_page(self):
        client = EastmoneyClient(page_size=200, page_delay=0)
        responses = [
            {
                "data": {
                    "diff": [
                        {"f12": "000001", "f13": 0, "f14": "股票1", "f62": 1},
                    ]
                }
            },
            {"data": {"diff": []}},
        ]

        with patch.object(client, "_get_with_retry", side_effect=responses) as request:
            results = client.fetch_all_stock_fund_flow()

        self.assertEqual(len(results), 1)
        self.assertEqual(request.call_count, 2)


    def test_rejects_pages_with_duplicate_stock_codes(self):
        client = EastmoneyClient(page_size=2, page_delay=0)
        responses = [
            {
                "data": {
                    "total": 3,
                    "diff": [
                        {"f12": "000001", "f13": 0, "f14": "平安银行", "f62": 1},
                        {"f12": "600000", "f13": 1, "f14": "浦发银行", "f62": 2},
                    ],
                }
            },
            {
                "data": {
                    "total": 3,
                    "diff": [
                        {"f12": "600000", "f13": 1, "f14": "浦发银行", "f62": 2},
                    ],
                }
            },
        ]

        with patch.object(client, "_get_with_retry", side_effect=responses):
            self.assertEqual(client.fetch_all_stock_fund_flow(), [])

    @patch("fundflow.services.eastmoney_client.requests.Session")
    def test_owned_sessions_are_isolated_per_worker_thread(self, session_class):
        sessions = [Mock(name="session_one"), Mock(name="session_two")]
        session_class.side_effect = sessions
        client = EastmoneyClient()
        barrier = threading.Barrier(2)
        observed = []

        def read_session():
            barrier.wait()
            observed.append(client._get_session())

        threads = [threading.Thread(target=read_session) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertCountEqual(observed, sessions)

    def test_requests_reuse_the_same_session(self):
        response = Mock()
        response.json.return_value = {"data": {"diff": []}}
        session = Mock()
        session.get.return_value = response
        client = EastmoneyClient(session=session)

        result = client._get_with_retry({"pn": 1})

        self.assertEqual(result, {"data": {"diff": []}})
        session.get.assert_called_once()
        response.raise_for_status.assert_called_once_with()

    def test_transient_failures_use_exponential_backoff(self):
        response = Mock()
        response.json.return_value = {"data": {"diff": []}}
        session = Mock()
        session.get.side_effect = [
            requests.exceptions.ProxyError("proxy disconnected"),
            requests.exceptions.ConnectionError("connection reset"),
            response,
        ]
        client = EastmoneyClient(
            session=session,
            max_retries=2,
            retry_backoff=2.0,
        )

        with patch("fundflow.services.eastmoney_client.time.sleep") as sleep:
            result = client._get_with_retry({"pn": 39})

        self.assertEqual(result, {"data": {"diff": []}})
        self.assertEqual(session.get.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(2.0), call(4.0)])


class EastmoneyClientConnectionRecoveryTests(SimpleTestCase):
    @patch("fundflow.services.eastmoney_client.requests.Session")
    def test_transport_failure_rebuilds_owned_session(self, session_class):
        failed_session = Mock()
        failed_session.get.side_effect = requests.exceptions.ProxyError(
            "proxy disconnected"
        )
        recovered_response = Mock()
        recovered_response.json.return_value = {"data": {"diff": []}}
        recovered_session = Mock()
        recovered_session.get.return_value = recovered_response
        session_class.side_effect = [failed_session, recovered_session]

        client = EastmoneyClient(max_retries=1, retry_backoff=0)
        result = client._get_with_retry({"pn": 24})

        self.assertEqual(result, {"data": {"diff": []}})
        failed_session.close.assert_called_once_with()
        recovered_session.get.assert_called_once()


class TradingTimeTests(SimpleTestCase):
    def _local_datetime(self, hour, minute):
        return timezone.make_aware(datetime(2026, 8, 19, hour, minute))

    def test_floors_live_snapshot_to_previous_15_minute_tick(self):
        self.assertEqual(
            floor_to_15min(self._local_datetime(9, 35)),
            self._local_datetime(9, 30),
        )
        self.assertEqual(
            floor_to_15min(self._local_datetime(10, 10)),
            self._local_datetime(10, 0),
        )
        self.assertEqual(
            floor_to_15min(self._local_datetime(11, 15)),
            self._local_datetime(11, 15),
        )

    def test_generates_every_previous_trading_tick(self):
        slots = trading_slots_until(
            date(2026, 8, 19),
            now=self._local_datetime(11, 25),
        )

        self.assertEqual(
            [timezone.localtime(slot).strftime("%H:%M") for slot in slots],
            ["09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15"],
        )

    def test_backfill_keeps_only_15_minute_ticks(self):
        points = [
            {"time": "09:30", "main_net_inflow": 1},
            {"time": "09:35", "main_net_inflow": 2},
            {"time": "09:45", "main_net_inflow": 3},
            {"time": "12:00", "main_net_inflow": 4},
            {"time": "13:00", "main_net_inflow": 5},
        ]

        self.assertEqual(
            [point["time"] for point in _downsample_to_15min(points)],
            ["09:30", "09:45", "13:00"],
        )


class TradingTimeAxisTests(TestCase):
    def setUp(self):
        cache.clear()

    def _local_datetime(self, hour, minute):
        return timezone.make_aware(datetime(2026, 8, 19, hour, minute))

    def _create_snapshot(self, hour, minute):
        StockFundFlowSnapshot.objects.create(
            stock_code=f"{hour:02d}{minute:04d}",
            stock_name="测试股票",
            market="SH",
            trade_date=date(2026, 8, 19),
            snapshot_time=self._local_datetime(hour, minute),
            main_net_inflow=1,
        )

    def test_axis_uses_all_elapsed_15_minute_ticks(self):
        for hour, minute in [(9, 30), (9, 35), (9, 45), (10, 0)]:
            self._create_snapshot(hour, minute)

        axis = get_trading_time_axis(
            date(2026, 8, 19),
            now=self._local_datetime(10, 5),
        )

        self.assertEqual(
            [timezone.localtime(slot).strftime("%H:%M") for slot in axis],
            ["09:30", "09:45", "10:00"],
        )

    def test_aggregation_uses_elapsed_ticks_and_forward_fills_missing_snapshots(self):
        sector = Sector.objects.create(code="TEST", name="测试板块")
        SectorConstituent.objects.create(
            sector=sector,
            stock_code="000001",
            stock_name="测试股票",
        )
        for hour, minute, value in [
            (9, 30, 100_000_000),
            (9, 35, 9_900_000_000),
            (10, 0, 300_000_000),
        ]:
            StockFundFlowSnapshot.objects.create(
                stock_code="000001",
                stock_name="测试股票",
                market="SZ",
                trade_date=date(2026, 8, 19),
                snapshot_time=self._local_datetime(hour, minute),
                main_net_inflow=value,
            )

        with patch(
            "fundflow.services.trading_time.timezone.now",
            return_value=self._local_datetime(10, 5),
        ):
            payload = aggregate_sector_intraday(
                date(2026, 8, 19),
                inflow_top=1,
                outflow_top=0,
            )

        self.assertEqual(payload["time_points"], ["09:30", "09:45", "10:00"])
        self.assertEqual(payload["series"][0]["data"], [1.0, 1.0, 3.0])



    def test_marks_payload_stale_when_expected_slots_are_missing(self):
        sector = Sector.objects.create(code="STALE", name="陈旧板块")
        SectorConstituent.objects.create(
            sector=sector,
            stock_code="000001",
            stock_name="测试股票",
        )
        StockFundFlowSnapshot.objects.create(
            stock_code="000001",
            stock_name="测试股票",
            market="SZ",
            trade_date=date(2026, 8, 19),
            snapshot_time=self._local_datetime(9, 30),
            main_net_inflow=100_000_000,
        )

        with patch(
            "fundflow.services.trading_time.timezone.now",
            return_value=self._local_datetime(10, 5),
        ):
            payload = aggregate_sector_intraday(
                date(2026, 8, 19), inflow_top=1, outflow_top=0
            )

        self.assertEqual(payload["time_points"], ["09:30", "09:45", "10:00"])
        self.assertTrue(payload["stale"])

    def test_historical_date_uses_all_eighteen_trading_slots(self):
        trade_date = date(2026, 8, 18)
        sector = Sector.objects.create(code="HISTORY", name="历史板块")
        SectorConstituent.objects.create(
            sector=sector,
            stock_code="000001",
            stock_name="测试股票",
        )
        for slot in trading_slots_for_day(trade_date):
            StockFundFlowSnapshot.objects.create(
                stock_code="000001",
                stock_name="测试股票",
                market="SZ",
                trade_date=trade_date,
                snapshot_time=slot,
                main_net_inflow=100_000_000,
            )

        payload = aggregate_sector_intraday(
            trade_date,
            inflow_top=1,
            outflow_top=0,
        )

        self.assertEqual(len(payload["time_points"]), 18)
        self.assertEqual(payload["time_points"][0], "09:30")
        self.assertEqual(payload["time_points"][-1], "15:00")
        self.assertFalse(payload["stale"])


class BackfillCompletenessTests(TestCase):
    def test_requires_every_canonical_slot(self):
        trade_date = date(2026, 8, 18)
        slots = trading_slots_for_day(trade_date)
        for index, slot in enumerate(slots[:16]):
            StockFundFlowSnapshot.objects.create(
                stock_code=f"{index:06d}",
                stock_name="测试股票",
                market="SH",
                trade_date=trade_date,
                snapshot_time=slot,
                main_net_inflow=1,
            )

        self.assertFalse(is_already_backfilled(trade_date))

        for index, slot in enumerate(slots[16:], start=16):
            StockFundFlowSnapshot.objects.create(
                stock_code=f"{index:06d}",
                stock_name="测试股票",
                market="SH",
                trade_date=trade_date,
                snapshot_time=slot,
                main_net_inflow=1,
            )

        self.assertTrue(is_already_backfilled(trade_date))


class LiveSnapshotCommandTests(TestCase):
    def test_command_stores_snapshot_at_floored_15_minute_tick(self):
        now = timezone.make_aware(datetime(2026, 8, 19, 10, 10))
        row = {
            "stock_code": "000001",
            "stock_name": "测试股票",
            "market": "SZ",
            "latest_price": 10,
            "change_pct": 1,
            "main_net_inflow": 100,
            "main_net_inflow_ratio": 2,
            "super_large_net_inflow": 10,
            "large_net_inflow": 20,
            "medium_net_inflow": 30,
            "small_net_inflow": 40,
        }

        with (
            patch(
                "fundflow.management.commands.fetch_stock_fund_flow.timezone.now",
                return_value=now,
            ),
            patch(
                "fundflow.management.commands.fetch_stock_fund_flow."
                "EastmoneyClient.fetch_all_stock_fund_flow",
                return_value=[row],
            ),
        ):
            call_command("fetch_stock_fund_flow", "--force")

        snapshot = StockFundFlowSnapshot.objects.get(stock_code="000001")
        self.assertEqual(
            timezone.localtime(snapshot.snapshot_time),
            timezone.make_aware(datetime(2026, 8, 19, 10, 0)),
        )


    def test_non_trading_time_returns_without_requesting_or_writing(self):
        now = timezone.make_aware(datetime(2026, 8, 19, 15, 30))

        with (
            patch(
                "fundflow.management.commands.fetch_stock_fund_flow.timezone.now",
                return_value=now,
            ),
            patch(
                "fundflow.management.commands.fetch_stock_fund_flow."
                "EastmoneyClient.fetch_all_stock_fund_flow"
            ) as fetch,
        ):
            call_command("fetch_stock_fund_flow")

        fetch.assert_not_called()
        self.assertFalse(StockFundFlowSnapshot.objects.exists())


class SectorIntradaySelectionTests(TestCase):
    def test_selects_inflow_and_outflow_leaders_independently(self):
        series = [
            {"code": "p10", "latest_net_inflow": 10},
            {"code": "p8", "latest_net_inflow": 8},
            {"code": "p6", "latest_net_inflow": 6},
            {"code": "zero", "latest_net_inflow": 0},
            {"code": "n1", "latest_net_inflow": -1},
            {"code": "n5", "latest_net_inflow": -5},
            {"code": "n7", "latest_net_inflow": -7},
        ]

        selected = select_sector_series(series, inflow_top=2, outflow_top=2)

        self.assertEqual(
            [item["code"] for item in selected],
            ["p10", "p8", "n7", "n5"],
        )

    def test_api_defaults_to_five_inflow_and_five_outflow_sectors(self):
        request = APIRequestFactory().get(
            "/api/sectors/intraday/",
            {"date": "2026-08-19"},
        )
        payload = {
            "trade_date": "2026-08-19",
            "time_points": [],
            "series": [],
            "stale": True,
        }

        with patch(
            "fundflow.views.aggregate_sector_intraday", return_value=payload
        ) as aggregate:
            response = SectorIntradayView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        aggregate.assert_called_once_with(
            trade_date=date(2026, 8, 19),
            inflow_top=5,
            outflow_top=5,
        )


    def test_api_defaults_to_latest_date_with_data(self):
        latest_date = date(2026, 8, 18)
        StockFundFlowSnapshot.objects.create(
            stock_code="000001",
            stock_name="测试股票",
            market="SZ",
            trade_date=latest_date,
            snapshot_time=timezone.make_aware(datetime(2026, 8, 18, 15, 0)),
            main_net_inflow=1,
        )
        request = APIRequestFactory().get("/api/sectors/intraday/")

        with patch(
            "fundflow.views.aggregate_sector_intraday",
            return_value={"time_points": [], "series": []},
        ) as aggregate:
            SectorIntradayView.as_view()(request)

        aggregate.assert_called_once_with(
            trade_date=latest_date,
            inflow_top=5,
            outflow_top=5,
        )

    def test_api_passes_explicit_inflow_and_outflow_limits(self):
        request = APIRequestFactory().get(
            "/api/sectors/intraday/",
            {
                "date": "2026-08-19",
                "inflow_top": "7",
                "outflow_top": "3",
            },
        )

        with patch(
            "fundflow.views.aggregate_sector_intraday",
            return_value={"time_points": [], "series": []},
        ) as aggregate:
            SectorIntradayView.as_view()(request)

        aggregate.assert_called_once_with(
            trade_date=date(2026, 8, 19),
            inflow_top=7,
            outflow_top=3,
        )
