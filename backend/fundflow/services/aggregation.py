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
from fundflow.services.trading_time import trading_slots_until

CACHE_TTL_SECONDS = 45
CACHE_VERSION_TTL_SECONDS = 2 * 24 * 60 * 60


def _cache_version_key(trade_date):
    return f"sector_intraday_version:{trade_date}"


def invalidate_sector_intraday_cache(trade_date):
    """写入新快照后更新交易日缓存版本，使所有数量组合立即读取新数据。"""
    cache.set(
        _cache_version_key(trade_date),
        timezone.now().timestamp(),
        timeout=CACHE_VERSION_TTL_SECONDS,
    )


def get_trading_time_axis(trade_date, now=None):
    """返回交易日截至当前时刻已经到达的全部标准 15 分钟刻度。"""
    return trading_slots_until(trade_date, now=now)


def select_sector_series(series, inflow_top, outflow_top):
    """分别选取净流入最高和净流出最多的板块，不把零值归入任一侧。"""
    inflows = sorted(
        (item for item in series if item["latest_net_inflow"] > 0),
        key=lambda item: item["latest_net_inflow"],
        reverse=True,
    )[:inflow_top]
    outflows = sorted(
        (item for item in series if item["latest_net_inflow"] < 0),
        key=lambda item: item["latest_net_inflow"],
    )[:outflow_top]
    return inflows + outflows


def aggregate_sector_intraday(trade_date, inflow_top=5, outflow_top=5):
    """
    聚合出某一天各行业板块的分时累计主力净流入曲线。

    返回结构：
    {
        "trade_date": "2026-08-18",
        "time_points": ["09:30", "09:45", ...],
        "series": [
            {"code": "CSV1e39751b68", "name": "半导体", "latest_net_inflow": 372.8, "data": [0, 1.2, ...]},
            ...
        ],
        "stale": false,
    }

    金额统一转换为"亿元"，与截图风格保持一致。
    "latest_net_inflow" 取曲线最后一个点的值，用于前端图例排序/着色。
    """
    time_axis = get_trading_time_axis(trade_date)
    axis_version = time_axis[-1].isoformat() if time_axis else "before_open"
    data_version = cache.get(_cache_version_key(trade_date), 0)
    cache_key = (
        f"sector_intraday:{trade_date}:{axis_version}:{data_version}:"
        f"{inflow_top}:{outflow_top}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if not time_axis:
        return {
            "trade_date": str(trade_date),
            "time_points": [],
            "series": [],
            "stale": True,
        }

    snapshot_qs = StockFundFlowSnapshot.objects.filter(
        trade_date=trade_date,
        snapshot_time__in=time_axis,
    )
    available_times = set(
        snapshot_qs.values_list("snapshot_time", flat=True).distinct()
    )
    if not available_times:
        return {
            "trade_date": str(trade_date),
            "time_points": [],
            "series": [],
            "stale": True,
        }

    stale = not set(time_axis).issubset(available_times)

    sectors = Sector.objects.all().prefetch_related("constituents")

    series = []
    for sector in sectors:
        stock_codes = [c.stock_code for c in sector.constituents.all()]
        if not stock_codes:
            continue

        rows = (
            snapshot_qs.filter(stock_code__in=stock_codes)
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

    selected_series = select_sector_series(
        series,
        inflow_top=inflow_top,
        outflow_top=outflow_top,
    )

    payload = {
        "trade_date": str(trade_date),
        "time_points": [timezone.localtime(t).strftime("%H:%M") for t in time_axis],
        "series": selected_series,
        "stale": stale,
    }
    cache.set(cache_key, payload, timeout=CACHE_TTL_SECONDS)
    return payload
