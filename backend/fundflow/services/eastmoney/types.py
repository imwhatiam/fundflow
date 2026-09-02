"""东方财富抓取流程的简单数据类型。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RequestIntervalPlan:
    """单次抓取预先生成的全部请求间隔。"""

    retry_delays: tuple[int, ...]
    successful_ranking_delay: int

    @property
    def total_seconds(self):
        """返回计划中所有可能使用的请求间隔总和。"""
        return sum(self.retry_delays) + self.successful_ranking_delay


@dataclass(frozen=True)
class SectorFundFlowFetchResult:
    """两次三级行业排行榜请求的合并数据及每个方向的可用性。"""

    rows: list[dict]
    inflow_succeeded: bool
    outflow_succeeded: bool
