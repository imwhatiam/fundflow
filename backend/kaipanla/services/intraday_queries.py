"""开盘啦板块分时查询所需的只读 ORM 操作。"""

from django.db.models import Max

from kaipanla.services.trading_time import trading_slots_for_day

from kaipanla.models import (
    KaipanlaSectorFundFlowSnapshot,
    KaipanlaSectorFundFlowSnapshotStatus,
)


def latest_snapshot_trade_date():
    """返回库中最近有开盘啦板块快照的交易日。"""
    return KaipanlaSectorFundFlowSnapshot.objects.using("kaipanla").aggregate(
        latest_date=Max("trade_date")
    )["latest_date"]


def load_close_snapshot_flow_rows(trade_dates):
    """读取固定交易日窗口中每个交易日 15:00 的板块主力净流入值。"""
    if not trade_dates:
        return []

    close_times = [trading_slots_for_day(trade_date)[-1] for trade_date in trade_dates]
    return KaipanlaSectorFundFlowSnapshot.objects.using("kaipanla").filter(
        trade_date__in=trade_dates,
        snapshot_time__in=close_times,
    ).order_by("-trade_date", "sector_code").values(
        "trade_date", "sector_code", "sector_name", "main_net_inflow"
    )


def list_latest_sectors(trade_date):
    """返回指定交易日最后一个快照内的板块列表。"""
    latest_time = KaipanlaSectorFundFlowSnapshot.objects.using("kaipanla").filter(
        trade_date=trade_date
    ).aggregate(latest_time=Max("snapshot_time"))["latest_time"]
    if latest_time is None:
        return []

    sectors = KaipanlaSectorFundFlowSnapshot.objects.using("kaipanla").filter(
        trade_date=trade_date,
        snapshot_time=latest_time,
    ).order_by("sector_name").values("sector_code", "sector_name")
    return [{"code": sector["sector_code"], "name": sector["sector_name"]} for sector in sectors]


def load_intraday_snapshot_rows(trade_date, time_axis):
    """读取时间轴内各板块快照，返回最小化字段字典。"""
    return KaipanlaSectorFundFlowSnapshot.objects.using("kaipanla").filter(
        trade_date=trade_date,
        snapshot_time__in=time_axis,
    ).values("sector_code", "sector_name", "snapshot_time", "main_net_inflow")


def load_intraday_status_rows(trade_date, time_axis):
    """读取时间轴内每个刻度的抓取完整性。"""
    return KaipanlaSectorFundFlowSnapshotStatus.objects.using("kaipanla").filter(
        trade_date=trade_date,
        snapshot_time__in=time_axis,
    ).values("snapshot_time", "fetch_succeeded")
