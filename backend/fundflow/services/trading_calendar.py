"""A 股交易日判断的统一入口。"""

from datetime import timedelta

from chinese_calendar import is_workday


def is_a_share_trading_day(value):
    """按中国法定节假日判断是否可能为 A 股交易日。

    ``chinese-calendar`` 会将调休周末标记为工作日；A 股周末不开市，因此仍需排除
    周六、周日。交易所临时休市等例外不在该库的法定节假日数据范围内。
    """
    return value.weekday() < 5 and is_workday(value)


def previous_a_share_trading_day(value):
    """返回 ``value`` 之前最近一个可能的 A 股交易日。"""
    candidate = value - timedelta(days=1)
    while not is_a_share_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def trading_day_window(end_date, *, count):
    """返回以结束日期为准、从新到旧的固定 A 股交易日窗口。

    非交易日会向前回退到最近一个交易日，结果始终包含 ``count`` 个交易日。
    """
    if count < 1:
        return []

    candidate = end_date
    while not is_a_share_trading_day(candidate):
        candidate -= timedelta(days=1)

    trade_dates = []
    while len(trade_dates) < count:
        trade_dates.append(candidate)
        candidate = previous_a_share_trading_day(candidate)
    return trade_dates
