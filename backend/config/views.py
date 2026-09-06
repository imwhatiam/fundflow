"""与具体数据源无关的共享 API 视图。

A 股交易日判断对东方财富和开盘啦两个数据源是同一套规则，因此放在项目层，
避免出现第三个交易日历实现。交易日历本身仍由 ``fundflow.services.trading_calendar``
提供（两个数据源 app 各自持有等价实现，互为独立）。
"""

import datetime

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from fundflow.services.trading_calendar import (
    is_a_share_trading_day,
    resolve_trading_day,
)


def _parse_date_param(request):
    """读取 ISO 日期；缺失或无效时使用服务端本地日期。"""
    date_str = request.query_params.get("date")
    if date_str:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            pass

    return timezone.localdate()


class TradingDayView(APIView):
    """GET /fundflow-api/trading-day/：把给定日期回退到最近的 A 股交易日。"""

    def get(self, request):
        requested_date = _parse_date_param(request)
        return Response(
            {
                "requested_date": requested_date.isoformat(),
                "date": resolve_trading_day(requested_date).isoformat(),
                "is_trading_day": is_a_share_trading_day(requested_date),
            }
        )
