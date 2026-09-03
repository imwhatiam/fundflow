"""开盘啦板块排行（RealRankingInfo）的分页请求、重试和结果合并。"""

import logging

import requests

from django.conf import settings

from .constants import (
    KAIPANLA_API_VERSION,
    KAIPANLA_MAX_RETRIES,
    KAIPANLA_PHONE_OS_NEW,
    KAIPANLA_RANKING_ACTION,
    KAIPANLA_RANKING_CONTROLLER,
    KAIPANLA_RANKING_PAGE_SIZE,
    KAIPANLA_RANKING_TYPE,
    KAIPANLA_RANKING_ZSTYPE,
    KAIPANLA_RETRY_BASE_DELAY_SECONDS,
    KAIPANLA_VERSION,
)
from .http_client import KaipanlaHttpClient
from .parser import parse_sector_row
from .types import KaipanlaSectorFundFlowFetchResult

logger = logging.getLogger(__name__)


class KaipanlaRankingFetcher:
    """按页串行拉取开盘啦全量板块排行，并在板块代码上去重。"""

    def __init__(self, *, timeout=15, session=None, http_client=None, sleep=None):
        self.http_client = http_client or KaipanlaHttpClient(timeout=timeout, session=session)
        self.sleep = sleep or __import__("time").sleep

    def fetch_sector_fund_flow(self):
        """抓取全量板块并返回合并后的数据与完整性。"""
        rows_by_code = {}
        source_timestamp = None
        source_trade_date = None
        skipped_rows = 0
        total_count = None
        page = 0

        while True:
            params = self._build_page_params(page)
            response = self._post_with_retry(params)
            if response is None:
                return KaipanlaSectorFundFlowFetchResult(
                    rows=[],
                    fetch_succeeded=False,
                    source_timestamp=None,
                    source_trade_date=None,
                )

            errcode = str(response.get("errcode", "0"))
            if errcode != "0":
                logger.error("开盘啦 RealRankingInfo 返回 errcode=%s: %s", errcode, response.get("errmsg", ""))
                return KaipanlaSectorFundFlowFetchResult(
                    rows=[],
                    fetch_succeeded=False,
                    source_timestamp=source_timestamp,
                    source_trade_date=source_trade_date,
                )

            day_list = response.get("Day") or []
            if day_list and source_trade_date is None:
                source_trade_date = str(day_list[0])

            time_value = response.get("Time")
            if time_value is not None and source_timestamp is None:
                source_timestamp = time_value

            if total_count is None:
                total_count = self._parse_count(response.get("Count"))

            items = response.get("list") or []
            if not items:
                break

            for raw_row in items:
                parsed_row = parse_sector_row(raw_row)
                if parsed_row is None:
                    skipped_rows += 1
                    continue
                rows_by_code[parsed_row["sector_code"]] = parsed_row

            page += 1
            if total_count is not None and page * KAIPANLA_RANKING_PAGE_SIZE >= total_count:
                break

        if skipped_rows:
            logger.warning("开盘啦板块排行清洗时丢弃 %d 条记录", skipped_rows)

        fetch_succeeded = bool(rows_by_code)
        if not fetch_succeeded:
            logger.error("开盘啦板块排行分页抓取未获得任何有效记录")

        return KaipanlaSectorFundFlowFetchResult(
            rows=list(rows_by_code.values()),
            fetch_succeeded=fetch_succeeded,
            source_timestamp=source_timestamp,
            source_trade_date=source_trade_date,
        )

    def _post_with_retry(self, params):
        last_error = None
        for attempt in range(1, KAIPANLA_MAX_RETRIES + 1):
            try:
                return self.http_client.post_json(params)
            except (requests.RequestException, ValueError) as error:
                last_error = error
                logger.warning("开盘啦接口请求失败(第%d/%d次): %s", attempt, KAIPANLA_MAX_RETRIES, error)
                if attempt < KAIPANLA_MAX_RETRIES:
                    self.sleep(KAIPANLA_RETRY_BASE_DELAY_SECONDS)
        logger.error("开盘啦接口多次重试后仍失败: %s", last_error)
        return None

    def _build_page_params(self, page):
        params = {
            "Order": "1",
            "a": KAIPANLA_RANKING_ACTION,
            "st": str(KAIPANLA_RANKING_PAGE_SIZE),
            "c": KAIPANLA_RANKING_CONTROLLER,
            "PhoneOSNew": KAIPANLA_PHONE_OS_NEW,
            "DeviceID": settings.KAIPANLA_DEVICE_ID,
            "VerSion": KAIPANLA_VERSION,
            "Index": str(page * KAIPANLA_RANKING_PAGE_SIZE),
            "apiv": KAIPANLA_API_VERSION,
            "Type": KAIPANLA_RANKING_TYPE,
            "ZSType": KAIPANLA_RANKING_ZSTYPE,
        }
        if settings.KAIPANLA_USER_ID:
            params["UserID"] = settings.KAIPANLA_USER_ID
        if settings.KAIPANLA_TOKEN:
            params["Token"] = settings.KAIPANLA_TOKEN
        return params

    @staticmethod
    def _parse_count(raw_count):
        try:
            return int(raw_count)
        except (TypeError, ValueError):
            return None
