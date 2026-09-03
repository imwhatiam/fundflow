"""开盘啦板块资金流请求使用的固定参数。

实时行情域名 apphwshhq.longhuvip.com 与历史域名 apphis.longhuvip.com 返回的
RealRankingInfo 字段结构一致；实时链路不带 Date 参数即可拿到当前盘中快照。
"""

# 实时行情端点（用于抓取板块资金流与校验 Token）。
KAIPANLA_HQ_URL = "https://apphwshhq.longhuvip.com/w1/api/index.php"

# 认证与客户端版本参数，与 App 抓包一致。
KAIPANLA_VERSION = "5.23.0.4"
KAIPANLA_API_VERSION = "w44"
KAIPANLA_PHONE_OS_NEW = "1"

# 板块排行请求参数。
KAIPANLA_RANKING_ACTION = "RealRankingInfo"
KAIPANLA_RANKING_CONTROLLER = "ZhiShuRanking"
KAIPANLA_RANKING_PAGE_SIZE = 30
KAIPANLA_RANKING_TYPE = "1"
KAIPANLA_RANKING_ZSTYPE = "7"

# 单页抓取失败后的重试次数与固定退避（开盘啦单接口分页，无东财的跨榜单编排）。
KAIPANLA_MAX_RETRIES = 3
KAIPANLA_RETRY_BASE_DELAY_SECONDS = 1.5

HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; ALN-AL00 Build/W528JS)",
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip",
}
