"""兼容旧导入路径的三级行业分时查询入口。"""

from fundflow.services.sector_intraday_builders import select_sector_series
from fundflow.services.sector_intraday_cache import (
    get_sector_intraday_cache_timeout,
    invalidate_sector_intraday_cache,
)
from fundflow.services.sector_intraday_service import (
    get_trading_time_axis,
    query_sector_intraday,
)

# 保留旧公开函数名，避免现有调用方在结构重构时中断。
aggregate_sector_intraday = query_sector_intraday

__all__ = [
    "aggregate_sector_intraday",
    "get_sector_intraday_cache_timeout",
    "get_trading_time_axis",
    "invalidate_sector_intraday_cache",
    "select_sector_series",
]
