"""东方财富行业板块分时资金流的查询、对齐和 Top N 选择。"""

from collections import defaultdict
from math import ceil

from django.core.cache import cache
from django.utils import timezone

from fundflow.models import EastmoneySectorFundFlowSnapshot
from fundflow.services.trading_time import trading_slots_for_day, trading_slots_until

# 当前交易日的缓存会在下一交易刻度自动失效；历史数据仅在写入新快照时失效。
HISTORICAL_CACHE_TTL_SECONDS = 2 * 24 * 60 * 60
CACHE_VERSION_TTL_SECONDS = 2 * 24 * 60 * 60


def _cache_version_key(trade_date):
    return f"sector_intraday_version:{trade_date}"


def invalidate_sector_intraday_cache(trade_date):
    """写入新板块快照后更新交易日缓存版本。"""
    cache.set(
        _cache_version_key(trade_date),
        timezone.now().timestamp(),
        timeout=CACHE_VERSION_TTL_SECONDS,
    )


def get_trading_time_axis(trade_date, now=None):
    """返回交易日截至当前时刻已经到达的全部标准 15 分钟刻度。"""
    return trading_slots_until(trade_date, now=now)


def get_sector_intraday_cache_timeout(trade_date, now=None):
    """返回缓存有效期；当前交易日精确持续到下一个 15 分钟交易刻度。"""
    now = now or timezone.now()
    if timezone.is_naive(now):
        now = timezone.make_aware(now)
    now_local = timezone.localtime(now)

    if trade_date != now_local.date():
        return HISTORICAL_CACHE_TTL_SECONDS

    next_slot = next(
        (slot for slot in trading_slots_for_day(trade_date) if slot > now_local),
        None,
    )
    if next_slot is None:
        return HISTORICAL_CACHE_TTL_SECONDS

    return max(1, ceil((next_slot - now_local).total_seconds()))


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


def _empty_payload(trade_date):
    return {
        "trade_date": str(trade_date),
        "time_points": [],
        "series": [],
        "stale": True,
    }


def aggregate_sector_intraday(trade_date, inflow_top=5, outflow_top=5):
    """
    返回东方财富行业板块的分时累计主力净流入曲线。

    数据在抓取时已是板块粒度；金额由元转换为亿元。
    缺失时间点以前一个已知值前向填充，避免局部抓取失败时曲线出现人为归零。
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
        return _empty_payload(trade_date)

    rows = EastmoneySectorFundFlowSnapshot.objects.filter(
        trade_date=trade_date,
        snapshot_time__in=time_axis,
    ).values("sector_code", "sector_name", "snapshot_time", "main_net_inflow")

    values_by_sector = defaultdict(dict)
    names_by_sector = {}
    available_times = set()
    for row in rows:
        code = row["sector_code"]
        names_by_sector[code] = row["sector_name"]
        values_by_sector[code][row["snapshot_time"]] = float(row["main_net_inflow"])
        available_times.add(row["snapshot_time"])

    if not values_by_sector:
        return _empty_payload(trade_date)

    # 完整快照应覆盖全部刻度；仅有部分板块时仍尽量返回已有板块，同时告知前端数据陈旧。
    stale = not set(time_axis).issubset(available_times)
    series = []
    for code, value_by_time in values_by_sector.items():
        aligned_yi = []
        last_value = 0.0
        for snapshot_time in time_axis:
            if snapshot_time in value_by_time:
                last_value = value_by_time[snapshot_time]
            aligned_yi.append(round(last_value / 1e8, 4))

        series.append(
            {
                "code": code,
                "name": names_by_sector[code],
                "latest_net_inflow": aligned_yi[-1],
                "data": aligned_yi,
            }
        )

    payload = {
        "trade_date": str(trade_date),
        "time_points": [timezone.localtime(point).strftime("%H:%M") for point in time_axis],
        "series": select_sector_series(series, inflow_top, outflow_top),
        "stale": stale,
    }
    cache.set(
        cache_key,
        payload,
        timeout=get_sector_intraday_cache_timeout(trade_date),
    )
    return payload
