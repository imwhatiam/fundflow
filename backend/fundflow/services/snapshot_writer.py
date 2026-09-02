"""将已获取的三级行业数据作为一个快照写入数据库。"""

from dataclasses import dataclass

from django.db import transaction

from fundflow.models import (
    EastmoneySectorFundFlowSnapshot,
    EastmoneySectorFundFlowSnapshotStatus,
)
from fundflow.services.sector_intraday_cache import invalidate_sector_intraday_cache
from fundflow.services.eastmoney.types import SectorFundFlowFetchResult


@dataclass(frozen=True)
class SnapshotSaveResult:
    """描述一次快照保存的结果，供管理命令输出使用。"""

    saved: bool
    row_count: int


def model_values(row):
    """移除仅用于推断快照时刻的临时上游字段。"""
    return {key: value for key, value in row.items() if key != "source_timestamp"}


def save_sector_snapshot(*, snapshot_time, fetch_result: SectorFundFlowFetchResult):
    """原子 upsert 行业快照和方向状态，并在提交后失效查询缓存。"""
    if not fetch_result.rows:
        return SnapshotSaveResult(saved=False, row_count=0)

    trade_date = snapshot_time.date()
    snapshots = [
        EastmoneySectorFundFlowSnapshot(
            trade_date=trade_date,
            snapshot_time=snapshot_time,
            **model_values(row),
        )
        for row in fetch_result.rows
    ]

    with transaction.atomic():
        EastmoneySectorFundFlowSnapshot.objects.bulk_create(
            snapshots,
            update_conflicts=True,
            update_fields=[
                "trade_date",
                "sector_name",
                "latest_index",
                "change_pct",
                "main_net_inflow",
                "main_net_inflow_ratio",
                "super_large_net_inflow",
                "large_net_inflow",
                "medium_net_inflow",
                "small_net_inflow",
            ],
            unique_fields=["sector_code", "snapshot_time"],
            batch_size=500,
        )
        EastmoneySectorFundFlowSnapshotStatus.objects.update_or_create(
            snapshot_time=snapshot_time,
            defaults={
                "trade_date": trade_date,
                "inflow_succeeded": fetch_result.inflow_succeeded,
                "outflow_succeeded": fetch_result.outflow_succeeded,
            },
        )
        transaction.on_commit(lambda: invalidate_sector_intraday_cache(trade_date))

    return SnapshotSaveResult(saved=True, row_count=len(snapshots))
