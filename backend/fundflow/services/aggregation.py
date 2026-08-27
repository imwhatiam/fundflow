"""东方财富行业板块分时资金流的查询、对齐和 Top N 选择。"""

from collections import defaultdict
from math import ceil

from django.core.cache import cache
from django.utils import timezone

from fundflow.models import (
    EastmoneySectorFundFlowSnapshot,
    EastmoneySectorFundFlowSnapshotStatus,
)
from fundflow.services.trading_time import trading_slots_for_day, trading_slots_until

# 当前交易日的缓存会在下一交易刻度自动失效；历史数据仅在写入新快照时失效。
HISTORICAL_CACHE_TTL_SECONDS = 2 * 24 * 60 * 60
CACHE_VERSION_TTL_SECONDS = 2 * 24 * 60 * 60
CACHE_KEY_SCHEMA_VERSION = "v2"


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


def _codes_with_direction(values_by_sector, snapshot_time, predicate):
    """返回在指定刻度实际出现且符合净流入方向的板块代码。"""
    return {
        code
        for code, value_by_time in values_by_sector.items()
        if snapshot_time in value_by_time and predicate(value_by_time[snapshot_time])
    }


def _direction_source_time(
    time_axis,
    values_by_sector,
    status_by_time,
    *,
    direction,
    predicate,
):
    """当前方向不可用时，严格回退到上一个 15 分钟刻度。"""
    current_time = time_axis[-1]
    current_status = status_by_time.get(current_time)
    current_request_succeeded = (
        current_status is None or current_status[f"{direction}_succeeded"]
    )
    current_codes = (
        _codes_with_direction(values_by_sector, current_time, predicate)
        if current_request_succeeded
        else set()
    )
    if current_codes:
        return current_time, current_codes, False

    if len(time_axis) < 2:
        return None, set(), True

    previous_time = time_axis[-2]
    previous_codes = _codes_with_direction(values_by_sector, previous_time, predicate)
    # 当前方向没有记录即代表该方向不完整；即便上一个刻度也没有可回退数据，
    # 响应仍必须明确标记为 stale。
    return previous_time, previous_codes, True


def _build_series_item(code, value_by_time, name, time_axis, source_time):
    """按时间轴前向填充，并在方向回退时把当前点固定为上个刻度的数据。"""
    current_time = time_axis[-1]
    aligned_yi = []
    last_value = 0.0
    for snapshot_time in time_axis:
        if snapshot_time in value_by_time:
            last_value = value_by_time[snapshot_time]
        aligned_yi.append(round(last_value / 1e8, 4))

    if source_time != current_time:
        # 该方向本刻度不可用；即使数据库遗留了旧重跑数据，也必须展示上个刻度的值。
        aligned_yi[-1] = round(value_by_time[source_time] / 1e8, 4)

    return {
        "code": code,
        "name": name,
        "latest_net_inflow": aligned_yi[-1],
        "data": aligned_yi,
    }


def aggregate_sector_intraday(trade_date, inflow_top=5, outflow_top=5):
    """
    返回东方财富行业板块的分时累计主力净流入曲线。

    数据在抓取时已是板块粒度；金额由元转换为亿元。
    缺失时间点以前一个已知值前向填充，避免局部抓取失败时曲线出现人为归零。
    当当前刻度的流入榜或流出榜请求失败（或没有该方向数据）时，只使用上一个刻度的该方向数据。
    """
    time_axis = get_trading_time_axis(trade_date)
    axis_version = time_axis[-1].isoformat() if time_axis else "before_open"
    data_version = cache.get(_cache_version_key(trade_date), 0)
    cache_key = (
        f"sector_intraday:{CACHE_KEY_SCHEMA_VERSION}:{trade_date}:{axis_version}:{data_version}:"
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

    statuses = EastmoneySectorFundFlowSnapshotStatus.objects.filter(
        trade_date=trade_date,
        snapshot_time__in=time_axis,
    ).values("snapshot_time", "inflow_succeeded", "outflow_succeeded")
    status_by_time = {item["snapshot_time"]: item for item in statuses}

    inflow_time, inflow_codes, inflow_missing = _direction_source_time(
        time_axis,
        values_by_sector,
        status_by_time,
        direction="inflow",
        predicate=lambda value: value > 0,
    )
    outflow_time, outflow_codes, outflow_missing = _direction_source_time(
        time_axis,
        values_by_sector,
        status_by_time,
        direction="outflow",
        predicate=lambda value: value < 0,
    )

    inflow_series = [
        _build_series_item(
            code,
            values_by_sector[code],
            names_by_sector[code],
            time_axis,
            inflow_time,
        )
        for code in inflow_codes
    ] if inflow_time else []
    outflow_series = [
        _build_series_item(
            code,
            values_by_sector[code],
            names_by_sector[code],
            time_axis,
            outflow_time,
        )
        for code in outflow_codes
    ] if outflow_time else []

    inflow_series.sort(key=lambda item: item["latest_net_inflow"], reverse=True)
    outflow_series.sort(key=lambda item: item["latest_net_inflow"])
    selected_inflows = inflow_series[:inflow_top]
    # 只排除实际显示在流入侧的板块；其余当前流入 Top 50 仍可作为上一刻度的流出候选。
    selected_inflow_codes = {item["code"] for item in selected_inflows}
    selected_outflows = [
        item for item in outflow_series if item["code"] not in selected_inflow_codes
    ][:outflow_top]
    current_status = status_by_time.get(time_axis[-1])
    stale = (
        not set(time_axis).issubset(available_times)
        or (current_status is not None and not (
            current_status["inflow_succeeded"] and current_status["outflow_succeeded"]
        ))
        or inflow_missing
        or outflow_missing
    )
    payload = {
        "trade_date": str(trade_date),
        "time_points": [timezone.localtime(point).strftime("%H:%M") for point in time_axis],
        "series": selected_inflows + selected_outflows,
        "stale": stale,
    }
    cache.set(
        cache_key,
        payload,
        timeout=get_sector_intraday_cache_timeout(trade_date),
    )
    return payload
