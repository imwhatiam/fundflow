"""三级行业分时接口的服务端缓存规则。"""

from math import ceil

from django.core.cache import cache
from django.utils import timezone

from fundflow.services.trading_time import trading_slots_for_day

HISTORICAL_CACHE_TTL_SECONDS = 2 * 24 * 60 * 60
CACHE_VERSION_TTL_SECONDS = 2 * 24 * 60 * 60
CACHE_KEY_SCHEMA_VERSION = "v2"


def invalidate_sector_intraday_cache(trade_date):
    """写入新快照后递增该交易日的缓存版本。"""
    cache.set(
        cache_version_key(trade_date),
        timezone.now().timestamp(),
        timeout=CACHE_VERSION_TTL_SECONDS,
    )


def cache_version_key(trade_date):
    """返回交易日数据版本的缓存 key。"""
    return f"sector_intraday_version:{trade_date}"


def sector_intraday_cache_key(*, trade_date, time_axis, data_version, inflow_top, outflow_top):
    """构造由时间轴、数据版本和 Top N 参数共同决定的缓存 key。"""
    axis_version = time_axis[-1].isoformat() if time_axis else "before_open"
    return (
        f"sector_intraday:{CACHE_KEY_SCHEMA_VERSION}:{trade_date}:{axis_version}:{data_version}:"
        f"{inflow_top}:{outflow_top}"
    )


def get_sector_intraday_cache_timeout(trade_date, now=None):
    """当前交易日缓存到下一交易刻度，历史数据缓存两天。"""
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
