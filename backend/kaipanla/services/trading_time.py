"""A股交易日的 15 分钟快照时间轴工具。"""

from datetime import datetime, time, timedelta

from django.utils import timezone

SNAPSHOT_INTERVAL_MINUTES = 15
TRADING_SESSIONS = (
    (time(9, 30), time(11, 30)),
    (time(13, 0), time(15, 0)),
)


def floor_to_15min(value):
    """将日期时间向下对齐到最近的 15 分钟刻度。"""
    minute = (value.minute // SNAPSHOT_INTERVAL_MINUTES) * SNAPSHOT_INTERVAL_MINUTES
    return value.replace(minute=minute, second=0, microsecond=0)


def is_15min_trading_clock(hour, minute):
    """判断时分是否为交易时段内的标准 15 分钟刻度。"""
    current = time(hour, minute)
    return minute % SNAPSHOT_INTERVAL_MINUTES == 0 and any(
        start <= current <= end for start, end in TRADING_SESSIONS
    )


def trading_slots_for_day(trade_date):
    """返回一个交易日的全部标准 15 分钟刻度。"""
    tz = timezone.get_current_timezone()
    slots = []
    for session_start, session_end in TRADING_SESSIONS:
        current = timezone.make_aware(datetime.combine(trade_date, session_start), tz)
        end = timezone.make_aware(datetime.combine(trade_date, session_end), tz)
        while current <= end:
            slots.append(current)
            current += timedelta(minutes=SNAPSHOT_INTERVAL_MINUTES)
    return slots


def trading_slots_until(trade_date, now=None):
    """返回交易日截至 ``now`` 已经到达的全部标准 15 分钟刻度。"""
    now = now or timezone.now()
    if timezone.is_naive(now):
        now = timezone.make_aware(now)
    now_local = timezone.localtime(now)

    if trade_date > now_local.date():
        return []

    slots = trading_slots_for_day(trade_date)
    if trade_date < now_local.date():
        return slots
    return [slot for slot in slots if slot <= now_local]
