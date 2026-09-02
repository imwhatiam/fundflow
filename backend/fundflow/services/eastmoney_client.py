"""兼容旧导入路径的东方财富三级行业抓取入口。

新代码应分别使用 services.eastmoney 中的 schedule、http_client、parser 和
ranking_fetcher 模块。该文件保留 EastmoneyClient 名称，避免命令或外部脚本
在重构发布时立即失效。
"""

from fundflow.services.eastmoney.constants import (
    EASTMONEY_CLIST_URL,
    EASTMONEY_RANKING_LIMIT,
    EASTMONEY_SECTOR_CLIST_UT,
    EASTMONEY_SECTOR_FS,
    HEADERS,
    MAX_FETCH_DURATION_SECONDS,
    MAX_REQUEST_INTERVAL_TOTAL_SECONDS,
    MAX_RETRIES,
    MIN_RETRY_INTERVAL_SECONDS,
    RETRY_INTERVAL_COUNT,
    SECTOR_FIELDS,
    SUCCESSFUL_RANKING_INTERVAL_SECONDS,
)
from fundflow.services.eastmoney.parser import parse_sector_row
from fundflow.services.eastmoney.ranking_fetcher import SectorRankingFetcher
from fundflow.services.eastmoney.request_schedule import prepare_interval_plan
from fundflow.services.eastmoney.types import RequestIntervalPlan, SectorFundFlowFetchResult


class EastmoneyClient(SectorRankingFetcher):
    """兼容名称；实际抓取编排由 SectorRankingFetcher 实现。"""

    _parse_sector_row = staticmethod(parse_sector_row)


__all__ = [
    "EASTMONEY_CLIST_URL",
    "EASTMONEY_RANKING_LIMIT",
    "EASTMONEY_SECTOR_CLIST_UT",
    "EASTMONEY_SECTOR_FS",
    "HEADERS",
    "MAX_FETCH_DURATION_SECONDS",
    "MAX_REQUEST_INTERVAL_TOTAL_SECONDS",
    "MAX_RETRIES",
    "MIN_RETRY_INTERVAL_SECONDS",
    "RETRY_INTERVAL_COUNT",
    "SECTOR_FIELDS",
    "SUCCESSFUL_RANKING_INTERVAL_SECONDS",
    "EastmoneyClient",
    "RequestIntervalPlan",
    "SectorFundFlowFetchResult",
    "prepare_interval_plan",
]
