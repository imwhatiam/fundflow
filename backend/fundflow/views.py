import datetime
import logging

from django.db.models import Max
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView

from fundflow.models import Sector, StockFundFlowSnapshot
from fundflow.serializers import SectorSerializer
from fundflow.services.aggregation import aggregate_sector_intraday

logger = logging.getLogger(__name__)


def _parse_date_param(request):
    """解析指定日期；缺省时返回数据库中最近一个有快照的交易日。"""
    date_str = request.query_params.get("date")
    if date_str:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            pass

    latest_date = StockFundFlowSnapshot.objects.aggregate(
        latest_date=Max("trade_date")
    )["latest_date"]
    return latest_date or timezone.localdate()


class SectorListView(ListAPIView):
    """GET /api/sectors/  行业板块列表"""

    serializer_class = SectorSerializer
    queryset = Sector.objects.all()


def _parse_limit_param(request, name, default):
    """解析板块曲线数量参数，允许传 0，并限制单侧最多返回 30 条。"""
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, 30))


class SectorIntradayView(APIView):
    """
    GET /api/sectors/intraday/?date=2026-08-18&inflow_top=5&outflow_top=5

    行业板块分时累计主力净流入曲线（对应截图"当日走势"图），实时从个股快照聚合得出。
    """

    def get(self, request):
        trade_date = _parse_date_param(request)
        inflow_top = _parse_limit_param(request, "inflow_top", 5)
        outflow_top = _parse_limit_param(request, "outflow_top", 5)

        payload = aggregate_sector_intraday(
            trade_date=trade_date,
            inflow_top=inflow_top,
            outflow_top=outflow_top,
        )
        return Response(payload)


class StockIntradayView(APIView):
    """
    GET /api/stocks/<code>/intraday/?date=2026-08-18

    单只个股当日分时累计主力净流入曲线（原始数据，不聚合）。
    """

    def get(self, request, code):
        trade_date = _parse_date_param(request)

        qs = (
            StockFundFlowSnapshot.objects.filter(stock_code=code, trade_date=trade_date)
            .order_by("snapshot_time")
        )
        if not qs.exists():
            return Response(
                {"detail": f"{code} 在 {trade_date} 没有数据（可能还未抓取，或代码不存在）"},
                status=404,
            )

        first = qs.first()
        return Response(
            {
                "stock_code": code,
                "stock_name": first.stock_name,
                "trade_date": str(trade_date),
                "time_points": [
                    timezone.localtime(row.snapshot_time).strftime("%H:%M") for row in qs
                ],
                "main_net_inflow": [round(float(row.main_net_inflow) / 1e8, 4) for row in qs],
                "latest_price": float(first.latest_price) if first.latest_price is not None else None,
            }
        )
