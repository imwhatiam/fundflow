"""东方财富行业板块资金流接口的薄封装。"""

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_SECTOR_CLIST_UT = "b2884a393a59ad64002292a3e90d46a5"
EASTMONEY_SECTOR_FS = "m:90+t:2"
SECTOR_FIELDS = (
    "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,"
    "f84,f87,f204,f205,f124"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}


class EastmoneyClient:
    """封装东方财富行业板块资金流请求，内置重试、分页完整性校验和字段清洗。"""

    def __init__(
        self,
        timeout=10,
        max_retries=5,
        page_size=200,
        page_delay=10.0,
        retry_backoff=5.0,
        max_retry_delay=60.0,
        session=None,
    ):
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        # 东财列表接口单页最多请求 200 条；是否完成始终按实际返回数量累计判断。
        self.page_size = max(1, min(page_size, 200))
        # 每个成功的上游请求后都等待，包含最后一页，避免短时间连续访问。
        self.page_delay = max(0, page_delay)
        self.retry_backoff = max(0, retry_backoff)
        self.max_retry_delay = max(0, max_retry_delay)
        self._owns_session = session is None
        self._provided_session = session
        self._session_local = threading.local()

    def fetch_all_sector_fund_flow(self):
        """分页拉取东方财富行业板块当日资金流，拒绝写入任何不完整结果。"""
        page = 1
        total = None
        raw_count = 0
        results = []
        skipped_rows = 0
        seen_codes = set()

        while True:
            data = self._get_with_retry(
                {
                    "po": 1,
                    "np": 1,
                    "fltt": 2,
                    "invt": 2,
                    "ut": EASTMONEY_SECTOR_CLIST_UT,
                    "fid0": "f62",
                    "fs": EASTMONEY_SECTOR_FS,
                    "stat": 1,
                    "fields": SECTOR_FIELDS,
                    "pn": page,
                    "pz": self.page_size,
                }
            )
            if not data:
                logger.error("东财行业板块资金流第 %d 页请求失败，放弃本次全量抓取", page)
                return []

            self._sleep_after_successful_request()
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
                        "东财行业板块资金流第 %d 页为空，已获取 %d/%d 条，放弃不完整结果",
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
                    logger.error("东财行业板块资金流分页出现重复代码 %s，放弃不完整结果", code)
                    return []
                if code:
                    seen_codes.add(code)

                parsed = self._parse_sector_row(row)
                if parsed:
                    results.append(parsed)
                else:
                    skipped_rows += 1

            logger.info(
                "东财行业板块资金流第 %d 页返回 %d 条，累计 %d%s",
                page,
                len(rows),
                raw_count,
                f"/{total}" if total is not None else "",
            )

            if total is not None and raw_count >= total:
                break

            page += 1

        if skipped_rows:
            logger.warning(
                "东财行业板块资金流原始记录 %d 条，清洗时丢弃 %d 条，"
                "将写入剩余 %d 条有效记录",
                raw_count,
                skipped_rows,
                len(results),
            )
        logger.info(
            "东财行业板块资金流共返回 %d 条原始记录，清洗后有效 %d 条",
            raw_count,
            len(results),
        )
        return results

    def _sleep_after_successful_request(self):
        """在上游请求成功后统一节流，最后一页同样等待。"""
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
