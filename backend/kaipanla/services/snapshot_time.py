"""决定开盘啦板块快照应写入的交易日和 5 分钟刻度。"""

from datetime import datetime, time

from django.utils import timezone

from kaipanla.services.trading_calendar import (
    is_a_share_trading_day,
    previous_a_share_trading_day,
)
from kaipanla.services.trading_time import trading_slots_for_day

MORNING_START = (9, 30)
MORNING_END = (11, 30)
AFTERNOON_START = (13, 0)
AFTERNOON_END = (15, 0)


def is_within_trading_hours(now_local):
    """判断当前是否处于 A 股交易时段，并排除非交易日。"""
    if not is_a_share_trading_day(now_local.date()):
        return False

    current_time = (now_local.hour, now_local.minute)
    return (MORNING_START <= current_time <= MORNING_END) or (
        AFTERNOON_START <= current_time <= AFTERNOON_END
    )


def fallback_latest_snapshot_time(now_local):
    """在缺少上游行情时间时，推断最近一个已结束的合法刻度。"""
    current_time = now_local.timetz().replace(tzinfo=None)
    if not is_a_share_trading_day(now_local.date()):
        previous_trade_date = previous_a_share_trading_day(now_local.date())
        return make_snapshot_time(previous_trade_date, time(15, 0))

    if current_time < time(9, 30):
        previous_trade_date = previous_a_share_trading_day(now_local.date())
        return make_snapshot_time(previous_trade_date, time(15, 0))
    if current_time < time(13, 0):
        return make_snapshot_time(now_local.date(), time(11, 30))
    return make_snapshot_time(now_local.date(), time(15, 0))


def align_to_latest_trading_slot(value):
    """将上游时间压到该交易日最近一个已经结束的交易刻度。"""
    if not is_a_share_trading_day(value.date()):
        return fallback_latest_snapshot_time(value)

    elapsed_slots = [slot for slot in trading_slots_for_day(value.date()) if slot <= value]
    if elapsed_slots:
        return elapsed_slots[-1]
    return fallback_latest_snapshot_time(value)


def latest_snapshot_time_from_source(source_timestamp, fallback_now_local):
    """优先根据开盘啦响应里的 ``Time`` 决定 --latest 的快照刻度。"""
    parsed_time = parse_source_timestamp(source_timestamp)
    if parsed_time is not None:
        return align_to_latest_trading_slot(parsed_time)
    return fallback_latest_snapshot_time(fallback_now_local)


def parse_source_timestamp(raw_timestamp):
    """解析秒级或毫秒级 Unix 时间戳；无效值返回 None。"""
    try:
        timestamp = float(raw_timestamp)
        if timestamp >= 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.get_current_timezone())
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def make_snapshot_time(trade_date, clock_time):
    """以项目当前时区创建一个可写入数据库的 aware datetime。"""
    return timezone.make_aware(datetime.combine(trade_date, clock_time))
