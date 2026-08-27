"""东方财富行业板块资金流接口的薄封装。"""

from dataclasses import dataclass
import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_SECTOR_CLIST_UT = "8dec03ba335b81bf4ebdf7b29ec27d15"
# 对应 data.eastmoney.com/bkzj/hy.html 的“行业”筛选，而非全部板块。
EASTMONEY_SECTOR_FS = "m:90+s:4"
EASTMONEY_RANKING_LIMIT = 50
SECTOR_FIELDS = (
    "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,"
    "f84,f87,f204,f205,f124"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/bkzj/hy.html",
}


@dataclass(frozen=True)
class SectorFundFlowFetchResult:
    """两次排行榜请求的合并数据及每个方向的可用性。"""

    rows: list[dict]
    inflow_succeeded: bool
    outflow_succeeded: bool


class EastmoneyClient:
    """封装东方财富行业资金流排行榜请求，并内置重试、节流和字段清洗。"""

    def __init__(
        self,
        timeout=10,
        max_retries=5,
        page_delay=10.0,
        ranking_interval=60.0,
        retry_backoff=5.0,
        max_retry_delay=60.0,
        session=None,
    ):
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        # 第二个排行榜成功后冷却，避免命令结束后立即由下一任务继续访问上游。
        self.page_delay = max(0, page_delay)
        # 两个独立 Top 50 请求之间的最小间隔，降低被上游短时限流的概率。
        self.ranking_interval = max(0, ranking_interval)
        self.retry_backoff = max(0, retry_backoff)
        self.max_retry_delay = max(0, max_retry_delay)
        self._owns_session = session is None
        self._provided_session = session
        self._session_local = threading.local()

    def fetch_sector_fund_flow_leaders(self):
        """分别获取净流入、净流出前 50 名，并用后一次响应覆盖重复板块。"""
        results_by_code = {}
        skipped_rows = 0
        succeeded = {"inflow": False, "outflow": False}
        rankings = (("资金流入", "inflow", 1), ("资金流出", "outflow", 0))

        # po=1 为 f62 降序（流入榜），po=0 为 f62 升序（流出榜）。
        for index, (ranking_name, result_key, sort_order) in enumerate(rankings):
            data = self._get_with_retry(
                {
                    "po": sort_order,
                    "np": 1,
                    "fltt": 2,
                    "invt": 2,
                    "ut": EASTMONEY_SECTOR_CLIST_UT,
                    "fid": "f62",
                    "fs": EASTMONEY_SECTOR_FS,
                    "stat": 1,
                    "fields": SECTOR_FIELDS,
                    "pn": 1,
                    "pz": EASTMONEY_RANKING_LIMIT,
                }
            )
            if not data:
                logger.warning(
                    "东财行业板块%s Top %d 请求失败，继续处理另一方向",
                    ranking_name,
                    EASTMONEY_RANKING_LIMIT,
                )
            else:
                payload = data.get("data") or {}
                rows = payload.get("diff") or []
                if isinstance(rows, dict):
                    rows = list(rows.values())

                if not rows:
                    logger.warning(
                        "东财行业板块%s Top %d 返回为空，标记该方向不完整",
                        ranking_name,
                        EASTMONEY_RANKING_LIMIT,
                    )
                else:
                    valid_count = 0
                    duplicate_count = 0
                    for row in rows:
                        parsed = self._parse_sector_row(row)
                        if not parsed:
                            skipped_rows += 1
                            continue

                        code = parsed["sector_code"]
                        if code in results_by_code:
                            duplicate_count += 1
                        # 流出榜后发；同一代码以这次更晚的响应为准。
                        results_by_code[code] = parsed
                        valid_count += 1

                    succeeded[result_key] = valid_count > 0
                    logger.info(
                        "东财行业板块%s Top %d 返回 %d 条原始记录，清洗后有效 %d 条，覆盖重复 %d 条",
                        ranking_name,
                        EASTMONEY_RANKING_LIMIT,
                        len(rows),
                        valid_count,
                        duplicate_count,
                    )

            if index == 0:
                self._sleep_between_rankings()
            elif data:
                self._sleep_after_successful_request()

        if skipped_rows:
            logger.warning(
                "东财行业板块两个排行榜清洗时丢弃 %d 条记录，将写入 %d 条有效记录",
                skipped_rows,
                len(results_by_code),
            )
        if not any(succeeded.values()):
            logger.error("东财行业板块资金流两个排行榜请求均失败或无有效数据")

        logger.info(
            "东财行业板块资金流排行榜有效 %d/2，合并后有效 %d 条",
            sum(succeeded.values()),
            len(results_by_code),
        )
        return SectorFundFlowFetchResult(
            rows=list(results_by_code.values()),
            inflow_succeeded=succeeded["inflow"],
            outflow_succeeded=succeeded["outflow"],
        )

    def _sleep_between_rankings(self):
        """在两个独立排行榜请求之间等待，失败后同样保持间隔。"""
        if self.ranking_interval:
            time.sleep(self.ranking_interval)

    def _sleep_after_successful_request(self):
        """在最后一个成功的上游排行榜请求后短暂冷却。"""
        if self.page_delay:
            time.sleep(self.page_delay)

    def _get_session(self):
        """返回当前线程专用的会话；外部注入会话保持原有共享语义。"""
        if not self._owns_session:
            return self._provided_session

        session = getattr(self._session_local, "session", None)
        if session is None:
            session = requests.Session()
            self._session_local.session = session
        return session

    def _reset_owned_session(self, failed_session):
        """只重建发生连接错误的线程会话，不影响其他线程。"""
        if not self._owns_session:
            return
        current = getattr(self._session_local, "session", None)
        if current is failed_session:
            current.close()
            self._session_local.session = requests.Session()

    def _get_with_retry(self, params):
        last_exc = None
        for attempt in range(1, self.max_retries + 2):
            session = self._get_session()
            try:
                response = session.get(
                    EASTMONEY_CLIST_URL,
                    params=params,
                    headers=HEADERS,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()
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
    def _parse_sector_row(row):
        def _num(key):
            value = row.get(key)
            return None if value in (None, "-", "") else value

        code = row.get("f12")
        main_net_inflow = _num("f62")
        if not code or main_net_inflow is None:
            return None

        return {
            "sector_code": code,
            "sector_name": row.get("f14") or "",
            "latest_index": _num("f2"),
            "change_pct": _num("f3"),
            "main_net_inflow": main_net_inflow,
            "main_net_inflow_ratio": _num("f184"),
            "super_large_net_inflow": _num("f66"),
            "large_net_inflow": _num("f72"),
            "medium_net_inflow": _num("f78"),
            "small_net_inflow": _num("f84"),
            # 仅用于非交易时段确定快照刻度，不写入模型。
            "source_timestamp": _num("f124"),
        }
