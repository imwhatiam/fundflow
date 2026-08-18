import datetime
import logging

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView

from fundflow.models import Sector, StockFundFlowSnapshot
from fundflow.serializers import SectorSerializer
from fundflow.services.aggregation import aggregate_sector_intraday

logger = logging.getLogger(__name__)


def _parse_date_param(request):
    """从 ?date=YYYY-MM-DD 解析交易日，缺省/解析失败时返回今天（本地时区）。"""
    date_str = request.query_params.get("date")
    if date_str:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            pass
    return timezone.localdate()


class SectorListView(ListAPIView):
    """GET /api/sectors/?category=industry  板块列表"""

    serializer_class = SectorSerializer

    def get_queryset(self):
        category = self.request.query_params.get("category", "industry")
        return Sector.objects.filter(category=category)


class SectorIntradayView(APIView):
    """
    GET /api/sectors/intraday/?category=industry&date=2026-08-18&top=10

    板块分时累计主力净流入曲线（对应截图"当日走势"图），实时从个股快照聚合得出。
    """

    def get(self, request):
        category = request.query_params.get("category", "industry")
        if category not in dict(Sector.CATEGORY_CHOICES):
            return Response(
                {"detail": f"不支持的板块类别: {category}，可选值: industry / concept"}, status=400
            )

        trade_date = _parse_date_param(request)

        try:
            top = int(request.query_params.get("top", 10))
        except ValueError:
            top = 10
        top = max(1, min(top, 30))  # 限制范围，避免一次性返回过多曲线拖垮前端渲染

        payload = aggregate_sector_intraday(category=category, trade_date=trade_date, top=top)
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
