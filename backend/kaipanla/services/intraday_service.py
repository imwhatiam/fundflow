"""开盘啦板块分时查询用例：缓存、读取和纯 payload 构造的协调层。"""

from django.core.cache import cache

from kaipanla.services.intraday_builders import build_kaipanla_intraday_payload
from kaipanla.services.intraday_cache import (
    cache_version_key,
    get_kaipanla_intraday_cache_timeout,
    kaipanla_intraday_cache_key,
)
from kaipanla.services.intraday_queries import (
    load_intraday_snapshot_rows,
    load_intraday_status_rows,
)
from kaipanla.services.trading_time import trading_slots_until


def get_trading_time_axis(trade_date, now=None):
    """返回交易日截至当前时刻已经到达的标准 15 分钟刻度。"""
    return trading_slots_until(trade_date, now=now)


def query_kaipanla_intraday(trade_date, inflow_top=5, outflow_top=5):
    """返回可缓存的开盘啦板块分时累计主力净流入 payload。"""
    time_axis = get_trading_time_axis(trade_date)
    data_version = cache.get(cache_version_key(trade_date), 0)
    cache_key = kaipanla_intraday_cache_key(
        trade_date=trade_date,
        time_axis=time_axis,
        data_version=data_version,
        inflow_top=inflow_top,
        outflow_top=outflow_top,
    )
    cached_payload = cache.get(cache_key)
    if cached_payload is not None:
        return cached_payload

    snapshot_rows = load_intraday_snapshot_rows(trade_date, time_axis)
    status_rows = load_intraday_status_rows(trade_date, time_axis)
    payload = build_kaipanla_intraday_payload(
        trade_date=trade_date,
        time_axis=time_axis,
        snapshot_rows=snapshot_rows,
        status_rows=status_rows,
        inflow_top=inflow_top,
        outflow_top=outflow_top,
    )
    cache.set(cache_key, payload, timeout=get_kaipanla_intraday_cache_timeout(trade_date))
    return payload
