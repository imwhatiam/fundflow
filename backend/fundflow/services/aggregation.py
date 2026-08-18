"""
板块级别资金流曲线的实时聚合逻辑。

核心思路：不单独存储/抓取板块资金流，而是拿 Sector -> SectorConstituent 的成分股映射，
去 StockFundFlowSnapshot 按 (板块, 时间点) 分组求和。因为映射关系是低频同步的静态数据，
这个聚合计算可以随时按需重新算，结果再做短TTL缓存即可，不用担心数据过期。
"""

from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

from fundflow.models import Sector, StockFundFlowSnapshot

CACHE_TTL_SECONDS = 45  # 略小于5分钟抓取间隔，保证轮询时基本能拿到最新一批数据，同时不会对DB造成太大压力


def get_trading_time_axis(trade_date):
    """返回某个交易日已经入库的全部快照时间点（去重、升序），作为所有板块曲线对齐的公共X轴。"""
    return list(
        StockFundFlowSnapshot.objects.filter(trade_date=trade_date)
        .values_list("snapshot_time", flat=True)
        .distinct()
        .order_by("snapshot_time")
    )


def aggregate_sector_intraday(category, trade_date, top=10):
    """
    聚合出某一天、某个板块类别下，各板块的分时累计主力净流入曲线。

    返回结构：
    {
        "trade_date": "2026-08-18",
        "category": "industry",
        "time_points": ["09:30", "09:35", ...],
        "series": [
            {"code": "BK0490", "name": "芯片", "latest_net_inflow": 372.8, "data": [0, 1.2, ...]},
            ...
        ],
        "stale": false,
    }

    金额统一转换为"亿元"，与截图风格保持一致。
    "latest_net_inflow" 取曲线最后一个点的值，用于前端图例排序/着色。
    """
    cache_key = f"sector_intraday:{category}:{trade_date}:{top}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    time_axis = get_trading_time_axis(trade_date)
    if not time_axis:
        return {
            "trade_date": str(trade_date),
            "category": category,
            "time_points": [],
            "series": [],
            "stale": True,
        }

    sectors = Sector.objects.filter(category=category).prefetch_related("constituents")

    series = []
    for sector in sectors:
        stock_codes = [c.stock_code for c in sector.constituents.all()]
        if not stock_codes:
            continue

        rows = (
            StockFundFlowSnapshot.objects.filter(trade_date=trade_date, stock_code__in=stock_codes)
            .values("snapshot_time")
            .annotate(total=Sum("main_net_inflow"))
            .order_by("snapshot_time")
        )
        value_by_time = {row["snapshot_time"]: float(row["total"]) for row in rows}
        if not value_by_time:
            continue

        # 按公共时间轴对齐，遇到某个时间点该板块暂无数据时，用上一个已知值前向填充，
        # 而不是填0——填0会在图上制造出不存在的"资金骤降到0"假象。
        aligned_yi = []  # 单位：亿元
        last_value = 0.0
        for t in time_axis:
            if t in value_by_time:
                last_value = value_by_time[t]
            aligned_yi.append(round(last_value / 1e8, 4))

        series.append(
            {
                "code": sector.code,
                "name": sector.name,
                "latest_net_inflow": aligned_yi[-1],
                "data": aligned_yi,
            }
        )

    # 按最新净流入的绝对值排序，取波动最大的 top 个（涨得最多的和跌得最多的都能露出来，
    # 而不是清一色只显示正向流入最多的），再按数值从大到小排列，方便图例展示。
    series.sort(key=lambda s: abs(s["latest_net_inflow"]), reverse=True)
    top_series = series[:top] if top else series
    top_series.sort(key=lambda s: s["latest_net_inflow"], reverse=True)

    payload = {
        "trade_date": str(trade_date),
        "category": category,
        "time_points": [timezone.localtime(t).strftime("%H:%M") for t in time_axis],
        "series": top_series,
        "stale": False,
    }
    cache.set(cache_key, payload, timeout=CACHE_TTL_SECONDS)
    return payload
