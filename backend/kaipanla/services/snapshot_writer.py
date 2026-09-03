"""将已获取的开盘啦板块数据作为一个快照写入独立数据库。"""

from dataclasses import dataclass

from django.db import transaction

from kaipanla.models import (
    KaipanlaSectorFundFlowSnapshot,
    KaipanlaSectorFundFlowSnapshotStatus,
)
from kaipanla.services.intraday_cache import invalidate_kaipanla_intraday_cache
from kaipanla.services.types import KaipanlaSectorFundFlowFetchResult


@dataclass(frozen=True)
class KaipanlaSnapshotSaveResult:
    """描述一次快照保存的结果，供管理命令输出使用。"""

    saved: bool
    row_count: int


def model_values(row):
    """移除仅用于推断快照时刻的临时上游字段。"""
    return {key: value for key, value in row.items() if key not in ("source_timestamp", "source_trade_date")}


def save_kaipanla_snapshot(*, snapshot_time, fetch_result: KaipanlaSectorFundFlowFetchResult):
    """原子 upsert 板块快照和状态，并在提交后失效查询缓存。"""
    if not fetch_result.rows:
        return KaipanlaSnapshotSaveResult(saved=False, row_count=0)

    trade_date = snapshot_time.date()
    snapshots = [
        KaipanlaSectorFundFlowSnapshot(
            trade_date=trade_date,
            snapshot_time=snapshot_time,
            **model_values(row),
        )
        for row in fetch_result.rows
    ]

    with transaction.atomic(using="kaipanla"):
        KaipanlaSectorFundFlowSnapshot.objects.using("kaipanla").bulk_create(
            snapshots,
            update_conflicts=True,
            update_fields=[
                "trade_date",
                "sector_name",
                "change_pct",
                "main_net_inflow",
                "main_buy",
                "main_sell",
                "large_order_net_inflow",
                "volume_ratio",
                "turnover_amount",
                "float_market_cap",
                "total_market_cap",
            ],
            unique_fields=["sector_code", "snapshot_time"],
            batch_size=500,
        )
        KaipanlaSectorFundFlowSnapshotStatus.objects.using("kaipanla").update_or_create(
            snapshot_time=snapshot_time,
            defaults={
                "trade_date": trade_date,
                "fetch_succeeded": fetch_result.fetch_succeeded,
            },
        )
        transaction.on_commit(
            lambda: invalidate_kaipanla_intraday_cache(trade_date),
            using="kaipanla",
        )

    return KaipanlaSnapshotSaveResult(saved=True, row_count=len(snapshots))
