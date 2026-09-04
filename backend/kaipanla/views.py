"""开盘啦板块 HTTP API 的参数解析和响应适配层。"""

import datetime

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from kaipanla.services.intraday_queries import (
    latest_snapshot_trade_date,
    list_latest_sectors,
)
from kaipanla.services.intraday_service import (
    query_kaipanla_intraday,
    query_kaipanla_intraday_history,
)


def _parse_date_param(request):
    """读取 ISO 日期；缺失或无效时回退到数据库中最近的交易日。"""
    date_str = request.query_params.get("date")
    if date_str:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            pass

    return latest_snapshot_trade_date() or timezone.localdate()


def _parse_history_days_param(request):
    """读取历史交易日数量，限制为前端支持的 1 至 20 天。"""
    try:
        value = int(request.query_params.get("days", 1))
    except (TypeError, ValueError):
        value = 1
    return max(1, min(value, 20))


def _parse_limit_param(request, name, default):
    """读取单侧曲线数量，允许 0，最大限制为 30。"""
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, 30))


class KaipanlaSectorIntradayHistoryView(APIView):
    """GET /kaipanla-api/sectors/intraday/history/：固定交易日窗口的分时数据。"""

    def get(self, request):
        end_date = _parse_date_param(request)
        days = _parse_history_days_param(request)
        inflow_top = _parse_limit_param(request, "inflow_top", 5)
        outflow_top = _parse_limit_param(request, "outflow_top", 5)
        payload = query_kaipanla_intraday_history(
            end_date=end_date,
            days=days,
            inflow_top=inflow_top,
            outflow_top=outflow_top,
        )
        return Response(payload)


class KaipanlaSectorListView(APIView):
    """GET /kaipanla-api/sectors/：最近快照中的开盘啦板块列表。"""

    def get(self, request):
        trade_date = _parse_date_param(request)
        return Response(list_latest_sectors(trade_date))


class KaipanlaSectorIntradayView(APIView):
    """GET /kaipanla-api/sectors/intraday/：开盘啦板块分时累计主力净流入曲线。"""

    def get(self, request):
        trade_date = _parse_date_param(request)
        inflow_top = _parse_limit_param(request, "inflow_top", 5)
        outflow_top = _parse_limit_param(request, "outflow_top", 5)
        payload = query_kaipanla_intraday(
            trade_date=trade_date,
            inflow_top=inflow_top,
            outflow_top=outflow_top,
        )
        return Response(payload)
