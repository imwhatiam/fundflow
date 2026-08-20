"""
东方财富未公开数据接口的薄封装。

说明：这些接口没有官方文档，字段编号（f12/f62/f184...）是社区逆向出来的，
东财随时可能调整字段或参数。真出问题时，用浏览器打开
https://data.eastmoney.com/zjlx/ ，开发者工具 Network 面板抓一下最新的
请求参数，对照更新本文件里的 EASTMONEY_CLIST_UT / FIELDS / DEFAULT_FS 即可，
不需要改动其它代码。
"""

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_CLIST_UT = "8dec03ba335b81bf4ebdf7b29ec27d15"

# 沪深京全市场 A 股过滤条件，与东财"资金流向-个股资金流"页面一致：
# m:0 深市, m:1 沪市, t: 板块细分(主板/创业板/科创板/北交所等)
DEFAULT_FS = (
    "m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,"
    "m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:7+f:!2,m:1+t:3+f:!2"
)

# 字段顺序与东财“个股资金流”页面当前的 clist/get 请求保持一致。
# f12=代码 f13=市场标识 f14=名称 f2=最新价 f3=涨跌幅(%)
# f62/f184=主力净流入金额/占比，f66/f69=超大单金额/占比，
# f72/f75=大单金额/占比，f78/f81=中单金额/占比，f84/f87=小单金额/占比。
FIELDS = (
    "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,"
    "f84,f87,f204,f205,f124,f1,f13"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}

# f13 市场标识 -> 交易所
MARKET_MAP = {0: "SZ", 1: "SH", 2: "BJ"}

EASTMONEY_STOCK_FFLOW_KLINE_URL = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"

# secid 的市场前缀：0=深圳 1=上海。北交所股票在东财内部实际使用的前缀不完全统一，
# 如果北交所股票请求这个接口总是返回空数据，需要用浏览器开发者工具抓包核实真实前缀。
SECID_MARKET_PREFIX = {"SZ": 0, "SH": 1, "BJ": 0}


class EastmoneyClient:
    """封装对东财资金流接口的调用，内置重试和字段清洗。"""

    def __init__(
        self,
        timeout=10,
        max_retries=5,
        page_size=200,
        page_delay=1.0,
        retry_backoff=5.0,
        max_retry_delay=60.0,
        session=None,
    ):
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        # 单页最多请求 200 条；是否完成始终按接口实际返回数量累计判断。
        self.page_size = max(1, min(page_size, 200))
        # 全市场约 27 页，轻微节流可降低东财或网络代理主动断开连接的概率。
        self.page_delay = max(0, page_delay)
        self.retry_backoff = max(0, retry_backoff)
        self.max_retry_delay = max(0, max_retry_delay)
        # 复用连接，避免每一页都重新进行 TCP/TLS/代理握手。自建会话在连接层
        # 出错后会重建，防止继续使用代理已经关闭的连接池。
        self._owns_session = session is None
        self._provided_session = session
        self._session_local = threading.local()

    def fetch_all_stock_fund_flow(self):
        """
        分页拉取全市场个股当日主力资金流快照。

        返回：list[dict]，每个 dict 是清洗后的单只股票数据；
        任意一页请求失败时返回空列表，避免调用方写入不完整的全市场快照。
        """
        page = 1
        total = None
        raw_count = 0
        results = []
        seen_codes = set()

        while True:
            params = {
                "pn": page,
                "pz": self.page_size,
                "po": 1,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "ut": EASTMONEY_CLIST_UT,
                # 使用稳定的股票代码排序，避免实时资金流变化导致跨页重复或漏股。
                "fid": "f12",
                "fs": DEFAULT_FS,
                "fields": FIELDS,
            }

            data = self._get_with_retry(params)
            if not data:
                logger.error("东财个股资金流第 %d 页请求失败，放弃本次全量抓取", page)
                return []

            payload = data.get("data") or {}
            rows = payload.get("diff") or []
            if isinstance(rows, dict):
                rows = list(rows.values())

            if total is None:
                try:
                    total = int(payload.get("total"))
                except (TypeError, ValueError):
                    total = None

            if not rows:
                if total is not None and raw_count < total:
                    logger.error(
                        "东财个股资金流第 %d 页为空，已获取 %d/%d 条，放弃不完整结果",
                        page,
                        raw_count,
                        total,
                    )
                    return []
                break

            raw_count += len(rows)
            for row in rows:
                code = row.get("f12")
                if code and code in seen_codes:
                    logger.error(
                        "东财个股资金流分页出现重复股票 %s，放弃不完整结果", code
                    )
                    return []
                if code:
                    seen_codes.add(code)

                parsed = self._parse_row(row)
                if parsed:
                    results.append(parsed)

            logger.info(
                "东财接口第 %d 页返回 %d 条，累计 %d%s",
                page,
                len(rows),
                raw_count,
                f"/{total}" if total is not None else "",
            )

            if total is not None and raw_count >= total:
                break

            page += 1
            if self.page_delay:
                time.sleep(self.page_delay)

        logger.info("东财接口共返回 %d 条原始记录，清洗后有效 %d 条", raw_count, len(results))
        return results

    def fetch_stock_intraday_history(self, stock_code, market):
        """
        获取单只个股"最近一个交易日"的完整分时资金流曲线（从开盘到当前/收盘的分钟级数据点）。

        跟 fetch_all_stock_fund_flow() 的区别：那个接口是全市场批量拉"当前这一个时间点"的快照，
        这个接口是针对单只股票拉"一整天"的时间序列，用于非交易时段的历史回补场景——
        比如服务刚部署、或者定时任务中断过一段时间，错过了当天盘中的多次15分钟快照，
        这时候可以用这个接口一次性把当天（或者收盘后=最近一个交易日）的完整曲线补回来。

        market: "SH"/"SZ"/"BJ"，用于拼接 secid。
        返回：list[{"time": "09:30", "main_net_inflow": ..., "super_large_net_inflow": ...,
                    "large_net_inflow": ..., "medium_net_inflow": ..., "small_net_inflow": ...}]
        请求失败或返回为空时返回空列表——调用方应该按"这只股票回补失败"处理，不要让单只
        股票的失败中断整批回补。
        """
        prefix = SECID_MARKET_PREFIX.get(market, 0)
        secid = f"{prefix}.{stock_code}"

        params = {
            "lmt": 0,  # 不限制条数，拿完整一天的数据
            "klt": 1,  # 分钟级
            "secid": secid,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        }
        data = self._get_with_retry(params, url=EASTMONEY_STOCK_FFLOW_KLINE_URL)
        if not data:
            return []

        klines = (data.get("data") or {}).get("klines") or []
        results = []
        for line in klines:
            parsed = self._parse_kline_row(line)
            if parsed:
                results.append(parsed)
        return results

    def _get_session(self):
        """返回当前线程专用的会话；外部注入的会话保持原有共享语义。"""
        if not self._owns_session:
            return self._provided_session

        session = getattr(self._session_local, "session", None)
        if session is None:
            session = requests.Session()
            self._session_local.session = session
        return session

    def _reset_owned_session(self, failed_session):
        """只重建当前线程发生连接错误的会话，不影响其它并发请求。"""
        if not self._owns_session:
            return
        current = getattr(self._session_local, "session", None)
        if current is failed_session:
            current.close()
            self._session_local.session = requests.Session()

    def _get_with_retry(self, params, url=None):
        target_url = url or EASTMONEY_CLIST_URL
        last_exc = None
        for attempt in range(1, self.max_retries + 2):
            session = self._get_session()
            try:
                resp = session.get(
                    target_url, params=params, headers=HEADERS, timeout=self.timeout
                )
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                if attempt <= self.max_retries:
                    if isinstance(exc, requests.exceptions.ConnectionError):
                        self._reset_owned_session(session)

                    delay = min(
                        self.retry_backoff * (2 ** (attempt - 1)),
                        self.max_retry_delay,
                    )
                    logger.warning(
                        "东财接口请求失败(第%d次尝试)，%.1f秒后重试: %s",
                        attempt,
                        delay,
                        exc,
                    )
                    if delay:
                        time.sleep(delay)
                else:
                    logger.warning("东财接口请求失败(第%d次尝试): %s", attempt, exc)
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

    @staticmethod
    def _parse_kline_row(line):
        """
        解析分时资金流kline的一行原始数据。东财这类接口把每个时间点的数据拼成一个逗号
        分隔的字符串，字段顺序对应请求参数里的 fields2：
        f51=时间, f52=主力净流入, f53=小单净流入, f54=中单净流入, f55=大单净流入,
        f56=超大单净流入，其余(f57-f61)是各类净占比，这里暂时用不上。

        这个字段顺序是参照东财"板块历史资金流"接口的公开资料整理的，个股分时接口的
        实际字段可能不完全一致——如果解析出来的数值明显不合理（比如全是0或None），
        用浏览器开发者工具抓包 `https://data.eastmoney.com/zjlx/detail/{code}.html`
        核实真实字段顺序，然后调整这里的下标映射。
        """
        parts = line.split(",")
        if len(parts) < 6:
            return None

        # 时间字段可能是 "09:30" 也可能是 "2026-08-19 09:30"，统一取最后的 "HH:MM"
        time_str = parts[0][-5:]

        def _to_float(s):
            try:
                return float(s)
            except (TypeError, ValueError):
                return None

        main_net_inflow = _to_float(parts[1])
        if main_net_inflow is None:
            return None

        return {
            "time": time_str,
            "main_net_inflow": main_net_inflow,
            "small_net_inflow": _to_float(parts[2]),
            "medium_net_inflow": _to_float(parts[3]),
            "large_net_inflow": _to_float(parts[4]),
            "super_large_net_inflow": _to_float(parts[5]),
        }

    # ------------------------------------------------------------------
    # 板块列表/成分股接口在这个项目里已不再使用——行业板块数据现在从本地CSV文件
    # （沪深京A股.csv）导入，见 fundflow/services/csv_import.py 和
    # fundflow/management/commands/sync_sectors.py。
    # ------------------------------------------------------------------
