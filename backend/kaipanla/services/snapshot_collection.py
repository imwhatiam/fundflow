"""协调开盘啦抓取结果与快照时刻，不直接写数据库。"""

from dataclasses import dataclass

from kaipanla.services.snapshot_time import latest_snapshot_time_from_source
from kaipanla.services.trading_time import floor_to_15min
from kaipanla.services.types import KaipanlaSectorFundFlowFetchResult


@dataclass(frozen=True)
class CollectedKaipanlaSnapshot:
    """抓取完成后可供预览或保存的快照内容。"""

    snapshot_time: object
    fetch_result: KaipanlaSectorFundFlowFetchResult


def collect_kaipanla_snapshot(*, now_local, latest_mode, fetcher):
    """抓取开盘啦板块数据，并决定本次快照的写入刻度。"""
    fetch_result = fetcher.fetch_sector_fund_flow()
    if latest_mode:
        snapshot_time = latest_snapshot_time_from_source(
            fetch_result.source_timestamp, now_local
        )
    else:
        snapshot_time = floor_to_15min(now_local)
    return CollectedKaipanlaSnapshot(snapshot_time=snapshot_time, fetch_result=fetch_result)
