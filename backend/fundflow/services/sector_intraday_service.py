"""三级行业分时查询用例：缓存、读取和纯 payload 构造的协调层。"""

from django.core.cache import cache

from fundflow.services.sector_intraday_builders import (
    build_sector_intraday_close_payload,
    build_sector_intraday_history_payload,
    build_period_rankings,
    build_sector_intraday_payload,
)
from fundflow.services.sector_intraday_cache import (
    cache_version_key,
    get_sector_intraday_cache_timeout,
    sector_intraday_cache_key,
)
from fundflow.services.sector_intraday_queries import (
    load_intraday_snapshot_rows,
    load_close_snapshot_flow_rows,
    load_intraday_status_rows,
)
from fundflow.services.trading_calendar import trading_day_window
from fundflow.services.trading_time import trading_slots_until


def get_trading_time_axis(trade_date, now=None):
    """返回交易日截至当前时刻已经到达的标准 15 分钟刻度。"""
    return trading_slots_until(trade_date, now=now)


def query_sector_intraday(trade_date, inflow_top=5, outflow_top=5, additional_codes=()):
    """返回可缓存的三级行业分时累计主力净流入 payload。"""
    time_axis = get_trading_time_axis(trade_date)
    data_version = cache.get(cache_version_key(trade_date), 0)
    cache_key = sector_intraday_cache_key(
        trade_date=trade_date,
        time_axis=time_axis,
        data_version=data_version,
        inflow_top=inflow_top,
        outflow_top=outflow_top,
        additional_codes=additional_codes,
    )
    cached_payload = cache.get(cache_key)
    if cached_payload is not None:
        return cached_payload

    snapshot_rows = load_intraday_snapshot_rows(trade_date, time_axis)
    status_rows = load_intraday_status_rows(trade_date, time_axis)
    payload = build_sector_intraday_payload(
        trade_date=trade_date,
        time_axis=time_axis,
        snapshot_rows=snapshot_rows,
        status_rows=status_rows,
        inflow_top=inflow_top,
        outflow_top=outflow_top,
        additional_codes=additional_codes,
    )
    cache.set(cache_key, payload, timeout=get_sector_intraday_cache_timeout(trade_date))
    return payload


def query_sector_intraday_history(end_date, days, inflow_top=5, outflow_top=5):
    """返回固定交易日窗口的 15:00 板块数据和窗口累计排行。"""
    trade_dates = trading_day_window(end_date, count=days)
    snapshot_rows = list(load_close_snapshot_flow_rows(trade_dates))
    period_rankings = build_period_rankings(
        snapshot_rows,
        inflow_top=inflow_top,
        outflow_top=outflow_top,
    )
    additional_codes = tuple(sorted({
        item["code"]
        for direction in ("inflows", "outflows")
        for item in period_rankings[direction]
    }))
    items = [
        build_sector_intraday_close_payload(
            query_sector_intraday(
                trade_date=trade_date,
                inflow_top=inflow_top,
                outflow_top=outflow_top,
                additional_codes=additional_codes,
            ),
            additional_codes,
        )
        for trade_date in trade_dates
    ]
    return build_sector_intraday_history_payload(
        end_date=end_date,
        items=items,
        period_rankings=period_rankings,
    )
