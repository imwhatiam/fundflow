"""开盘啦抓取流程的简单数据类型。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class KaipanlaSectorFundFlowFetchResult:
    """一次全量板块抓取的合并数据及完整性。"""

    rows: list[dict]
    fetch_succeeded: bool
    source_timestamp: float | None = None
    source_trade_date: str | None = None
