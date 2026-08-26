import datetime
import logging

from django.db.models import Max
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from fundflow.models import EastmoneySectorFundFlowSnapshot
from fundflow.services.aggregation import aggregate_sector_intraday

logger = logging.getLogger(__name__)


def _parse_date_param(request, snapshot_model):
    """解析日期；未提供或格式错误时使用指定数据源中最近一个有快照的交易日。"""
    date_str = request.query_params.get("date")
    if date_str:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            pass

    latest_date = snapshot_model.objects.aggregate(latest_date=Max("trade_date"))["latest_date"]
    return latest_date or timezone.localdate()


def _parse_limit_param(request, name, default):
    """解析板块曲线数量参数，允许传 0，并限制单侧最多返回 30 条。"""
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, 30))


class SectorListView(APIView):
    """GET /api/sectors/  最近快照中的东方财富行业板块列表。"""

    def get(self, request):
        trade_date = _parse_date_param(request, EastmoneySectorFundFlowSnapshot)
        latest_time = EastmoneySectorFundFlowSnapshot.objects.filter(
            trade_date=trade_date
        ).aggregate(latest_time=Max("snapshot_time"))["latest_time"]
        if latest_time is None:
            return Response([])

        sectors = EastmoneySectorFundFlowSnapshot.objects.filter(
            trade_date=trade_date,
            snapshot_time=latest_time,
        ).order_by("sector_name").values("sector_code", "sector_name")
        return Response(
            [
                {"code": item["sector_code"], "name": item["sector_name"]}
                for item in sectors
            ]
        )


class SectorIntradayView(APIView):
    """
    GET /api/sectors/intraday/?date=2026-08-18&inflow_top=5&outflow_top=5

    直接读取东方财富行业板块快照的分时累计主力净流入曲线。
    """

    def get(self, request):
        trade_date = _parse_date_param(request, EastmoneySectorFundFlowSnapshot)
        inflow_top = _parse_limit_param(request, "inflow_top", 5)
        outflow_top = _parse_limit_param(request, "outflow_top", 5)

        payload = aggregate_sector_intraday(
            trade_date=trade_date,
            inflow_top=inflow_top,
            outflow_top=outflow_top,
        )
        return Response(payload)
