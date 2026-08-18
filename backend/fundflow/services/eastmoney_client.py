"""
东方财富未公开数据接口的薄封装。

说明：这些接口没有官方文档，字段编号（f12/f62/f184...）是社区逆向出来的，
东财随时可能调整字段或参数。真出问题时，用浏览器打开
https://data.eastmoney.com/zjlx/ ，开发者工具 Network 面板抓一下最新的
请求参数，对照更新本文件里的 FIELDS / DEFAULT_FS 即可，不需要改动其它代码。
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

EASTMONEY_CLIST_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"

# 沪深京全市场 A 股过滤条件，与东财"资金流向-个股资金流"页面一致：
# m:0 深市, m:1 沪市, t: 板块细分(主板/创业板/科创板/北交所等)
DEFAULT_FS = (
    "m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,"
    "m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:7+f:!2,m:1+t:3+f:!2"
)

# f12=代码 f13=市场标识 f14=名称 f2=最新价 f3=涨跌幅(%)
# f62=今日主力净流入(元)      f184=主力净占比(%)
# f66=超大单净流入  f72=大单净流入  f78=中单净流入  f84=小单净流入
FIELDS = "f12,f13,f14,f2,f3,f62,f184,f66,f72,f78,f84"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}

# f13 市场标识 -> 交易所
MARKET_MAP = {0: "SZ", 1: "SH", 2: "BJ"}


class EastmoneyClient:
    """封装对东财资金流接口的调用，内置重试和字段清洗。"""

    def __init__(self, timeout=10, max_retries=2, page_size=6000):
        self.timeout = timeout
        self.max_retries = max_retries
        self.page_size = page_size  # 全市场A股约5000多只，一页取够即可，不用翻页

    def fetch_all_stock_fund_flow(self):
        """
        一次性拉取全市场个股当日主力资金流快照。

        返回：list[dict]，每个 dict 是清洗后的单只股票数据；
        请求失败（重试后仍失败）时返回空列表，调用方应据此判断本次抓取是否成功。
        """
        params = {
            "pn": 1,
            "pz": self.page_size,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "fid": "f62",
            "fs": DEFAULT_FS,
            "fields": FIELDS,
        }

        data = self._get_with_retry(params)
        if not data:
            return []

        rows = (data.get("data") or {}).get("diff") or []
        results = []
        for row in rows:
            parsed = self._parse_row(row)
            if parsed:
                results.append(parsed)

        logger.info("东财接口返回 %d 条原始记录，清洗后有效 %d 条", len(rows), len(results))
        return results

    def _get_with_retry(self, params):
        last_exc = None
        for attempt in range(1, self.max_retries + 2):
            try:
                resp = requests.get(
                    EASTMONEY_CLIST_URL, params=params, headers=HEADERS, timeout=self.timeout
                )
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                logger.warning("东财接口请求失败(第%d次尝试): %s", attempt, exc)
                if attempt <= self.max_retries:
                    time.sleep(1.5 * attempt)
        logger.error("东财接口多次重试后仍失败，放弃本次抓取: %s", last_exc)
        return None

    @staticmethod
    def _parse_row(row):
        def _num(key):
            val = row.get(key)
            if val in (None, "-", ""):
                return None
            return val

        code = row.get("f12")
        main_net_inflow = _num("f62")

        # 代码或主力净流入缺失的记录（通常是停牌/无成交）直接跳过，不污染数据表
        if not code or main_net_inflow is None:
            return None

        return {
            "stock_code": code,
            "stock_name": row.get("f14") or "",
            "market": MARKET_MAP.get(row.get("f13"), "UNKNOWN"),
            "latest_price": _num("f2"),
            "change_pct": _num("f3"),
            "main_net_inflow": main_net_inflow,
            "main_net_inflow_ratio": _num("f184"),
            "super_large_net_inflow": _num("f66"),
            "large_net_inflow": _num("f72"),
            "medium_net_inflow": _num("f78"),
            "small_net_inflow": _num("f84"),
        }

    # ------------------------------------------------------------------
    # 板块相关：板块列表 + 板块成分股。这两个接口调用频率很低（板块划分不常变），
    # 建议由单独的 sync_sectors 命令按天/按周同步，不要放进每5分钟一次的抓取里。
    # ------------------------------------------------------------------

    def fetch_sector_list(self, category="industry"):
        """
        获取板块列表（代码+名称）。
        category: "industry" -> 行业板块 (fs=m:90+t:2)， "concept" -> 概念板块 (fs=m:90+t:3)
        """
        fs_map = {"industry": "m:90+t:2", "concept": "m:90+t:3"}
        fs = fs_map.get(category)
        if not fs:
            raise ValueError(f"未知的板块类别: {category}")

        params = {
            "pn": 1,
            "pz": 500,  # 行业板块约90个、概念板块约几百个，500足够一页拿全
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "fid": "f3",
            "fs": fs,
            "fields": "f12,f14",  # f12=板块代码 f14=板块名称
        }
        data = self._get_with_retry(params)
        if not data:
            return []

        rows = (data.get("data") or {}).get("diff") or []
        return [
            {"code": row["f12"], "name": row["f14"]}
            for row in rows
            if row.get("f12") and row.get("f14")
        ]

    def fetch_sector_constituents(self, sector_code):
        """获取某个板块的成分股列表（代码+名称）。sector_code 如 'BK0490'。"""
        params = {
            "pn": 1,
            "pz": 1000,  # 单个板块成分股一般不超过几百只
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "fid": "f3",
            "fs": f"b:{sector_code}",
            "fields": "f12,f14",
        }
        data = self._get_with_retry(params)
        if not data:
            return []

        rows = (data.get("data") or {}).get("diff") or []
        return [
            {"stock_code": row["f12"], "stock_name": row["f14"]}
            for row in rows
            if row.get("f12")
        ]
