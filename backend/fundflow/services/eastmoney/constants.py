"""东方财富三级行业请求使用的固定参数。"""

EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_SECTOR_CLIST_UT = "8dec03ba335b81bf4ebdf7b29ec27d15"
# 东方财富行业页的三级行业筛选；不请求二级行业或混合板块。
EASTMONEY_SECTOR_FS = "m:90+s:8+f:!50"
EASTMONEY_RANKING_LIMIT = 50
SECTOR_FIELDS = (
    "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,"
    "f84,f87,f204,f205,f124"
)

MAX_RETRIES = 5
MIN_RETRY_INTERVAL_SECONDS = 45
SUCCESSFUL_RANKING_INTERVAL_SECONDS = 120
MAX_REQUEST_INTERVAL_TOTAL_SECONDS = 700
MAX_FETCH_DURATION_SECONDS = 889
RETRY_INTERVAL_COUNT = MAX_RETRIES * 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/bkzj/hy.html",
}
