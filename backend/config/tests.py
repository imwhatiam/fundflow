"""项目层共享 API 的契约测试。"""

from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import get_resolver
from rest_framework.test import APIRequestFactory

from config.views import TradingDayView


class TradingDayApiTests(SimpleTestCase):
    def test_trading_day_route_is_named(self):
        self.assertIn("trading-day", get_resolver().reverse_dict.keys())

    def test_trading_day_is_returned_unchanged(self):
        request = APIRequestFactory().get("/fundflow-api/trading-day/", {"date": "2026-08-19"})

        response = TradingDayView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "requested_date": "2026-08-19",
                "date": "2026-08-19",
                "is_trading_day": True,
            },
        )

    def test_weekend_falls_back_to_previous_friday(self):
        for weekend in ("2026-09-05", "2026-09-06"):
            with self.subTest(weekend=weekend):
                request = APIRequestFactory().get("/fundflow-api/trading-day/", {"date": weekend})

                response = TradingDayView.as_view()(request)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.data,
                    {
                        "requested_date": weekend,
                        "date": "2026-09-04",
                        "is_trading_day": False,
                    },
                )

    def test_missing_or_invalid_date_uses_server_local_date(self):
        for raw_date in (None, "not-a-date"):
            with self.subTest(raw_date=raw_date):
                params = {} if raw_date is None else {"date": raw_date}
                request = APIRequestFactory().get("/fundflow-api/trading-day/", params)

                with patch(
                    "config.views.timezone.localdate", return_value=date(2026, 9, 6)
                ):
                    response = TradingDayView.as_view()(request)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["date"], "2026-09-04")
                self.assertFalse(response.data["is_trading_day"])
