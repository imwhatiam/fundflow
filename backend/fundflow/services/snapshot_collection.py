"""协调抓取结果与快照时刻，不直接写数据库。"""

from dataclasses import dataclass

from fundflow.services.eastmoney.types import SectorFundFlowFetchResult
from fundflow.services.snapshot_time import latest_snapshot_time_from_source_rows
from fundflow.services.trading_time import floor_to_15min


@dataclass(frozen=True)
class CollectedSectorSnapshot:
    """抓取完成后可供预览或保存的快照内容。"""

    snapshot_time: object
    fetch_result: SectorFundFlowFetchResult


def collect_sector_snapshot(*, now_local, latest_mode, fetcher):
    """抓取三级行业数据，并决定本次快照的写入刻度。"""
    fetch_result = fetcher.fetch_sector_fund_flow_leaders()
    if latest_mode:
        snapshot_time = latest_snapshot_time_from_source_rows(fetch_result.rows, now_local)
    else:
        snapshot_time = floor_to_15min(now_local)
    return CollectedSectorSnapshot(snapshot_time=snapshot_time, fetch_result=fetch_result)
