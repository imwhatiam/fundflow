"""两份三级行业排行榜的请求编排、重试和结果合并。"""

import logging
import time

import requests

from .constants import (
    EASTMONEY_RANKING_LIMIT,
    EASTMONEY_SECTOR_CLIST_UT,
    EASTMONEY_SECTOR_FS,
    MAX_FETCH_DURATION_SECONDS,
    MAX_RETRIES,
    SECTOR_FIELDS,
)
from .http_client import EastmoneyHttpClient
from .parser import extract_ranking_rows, parse_sector_row
from .request_schedule import can_wait_until_deadline, prepare_interval_plan
from .types import SectorFundFlowFetchResult

logger = logging.getLogger(__name__)

RANKINGS = (
    ("资金流入", "inflow", 1),
    ("资金流出", "outflow", 0),
)


class SectorRankingFetcher:
    """按照受限间隔获取流入和流出 Top 50 三级行业排行榜。"""

    def __init__(
        self,
        timeout=10,
        session=None,
        *,
        http_client=None,
        interval_plan_factory=prepare_interval_plan,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.http_client = http_client or EastmoneyHttpClient(timeout=timeout, session=session)
        self.interval_plan_factory = interval_plan_factory
        self.sleep = sleep
        self.clock = clock

    def fetch_sector_fund_flow_leaders(self):
        """获取两份榜单。一个方向失败时保留另一个方向的数据。"""
        interval_plan = self.interval_plan_factory()
        deadline = self.clock() + MAX_FETCH_DURATION_SECONDS
        retry_delays = iter(interval_plan.retry_delays)
        rows_by_code = {}
        succeeded = {"inflow": False, "outflow": False}
        skipped_rows = 0

        logger.info(
            "三级行业请求间隔计划：10 个重试间隔与 1 个成功间隔共 %d 秒（上限 700 秒）",
            interval_plan.total_seconds,
        )

        for ranking_index, (ranking_name, direction, sort_order) in enumerate(RANKINGS):
            response = self._fetch_ranking_with_retry(
                build_ranking_params(sort_order),
                retry_delays=retry_delays,
                deadline=deadline,
            )
            ranking_rows, valid_count, discarded_count = self._parse_ranking_response(response, rows_by_code)
            skipped_rows += discarded_count
            succeeded[direction] = valid_count > 0
            self._log_ranking_result(ranking_name, response, ranking_rows, valid_count)

            if ranking_index == 0 and response is not None:
                if not self._wait_for_successful_ranking(interval_plan.successful_ranking_delay, deadline):
                    break

        self._log_fetch_summary(rows_by_code, succeeded, skipped_rows)
        return SectorFundFlowFetchResult(
            rows=list(rows_by_code.values()),
            inflow_succeeded=succeeded["inflow"],
            outflow_succeeded=succeeded["outflow"],
        )

    def _fetch_ranking_with_retry(self, params, *, retry_delays, deadline):
        """发送一份排行榜，初次失败后最多等待并重试五次。"""
        last_error = None
        for attempt_number in range(1, MAX_RETRIES + 2):
            remaining_seconds = deadline - self.clock()
            if remaining_seconds <= 0:
                logger.error("达到 890 秒总时限，放弃本次三级行业排行榜请求")
                break

            try:
                return self.http_client.get_json(params, timeout=remaining_seconds)
            except (requests.RequestException, ValueError) as error:
                last_error = error
                if attempt_number > MAX_RETRIES:
                    logger.warning("东财接口请求失败(第%d次尝试): %s", attempt_number, error)
                    break

                if isinstance(error, requests.exceptions.ConnectionError):
                    self.http_client.rebuild_session_after_connection_error()

                retry_delay = next(retry_delays)
                logger.warning(
                    "东财接口请求失败(第%d次尝试)，%d 秒后重试: %s",
                    attempt_number,
                    retry_delay,
                    error,
                )
                if not self._wait_within_deadline(retry_delay, deadline):
                    logger.error("890 秒总时限不足，放弃本次三级行业排行榜重试")
                    break

        logger.error("东财接口多次重试后仍失败，放弃本次抓取: %s", last_error)
        return None

    def _parse_ranking_response(self, response, rows_by_code):
        """解析一份成功响应，并让后发的流出榜覆盖重复行业。"""
        if response is None:
            return [], 0, 0

        raw_rows = extract_ranking_rows(response)
        valid_count = 0
        discarded_count = 0
        for raw_row in raw_rows:
            parsed_row = parse_sector_row(raw_row)
            if parsed_row is None:
                discarded_count += 1
                continue
            rows_by_code[parsed_row["sector_code"]] = parsed_row
            valid_count += 1
        return raw_rows, valid_count, discarded_count

    def _log_ranking_result(self, ranking_name, response, raw_rows, valid_count):
        if response is None:
            logger.warning(
                "东财三级行业%s Top %d 请求失败，继续处理另一方向",
                ranking_name,
                EASTMONEY_RANKING_LIMIT,
            )
        elif not raw_rows:
            logger.warning(
                "东财三级行业%s Top %d 返回为空，标记该方向不完整",
                ranking_name,
                EASTMONEY_RANKING_LIMIT,
            )
        else:
            logger.info(
                "东财三级行业%s Top %d 返回 %d 条原始记录，清洗后有效 %d 条",
                ranking_name,
                EASTMONEY_RANKING_LIMIT,
                len(raw_rows),
                valid_count,
            )

    def _log_fetch_summary(self, rows_by_code, succeeded, skipped_rows):
        """记录抓取结束后的汇总信息，不参与任何业务判断。"""
        if skipped_rows:
            logger.warning(
                "东财三级行业两个排行榜清洗时丢弃 %d 条记录，将写入 %d 条有效记录",
                skipped_rows,
                len(rows_by_code),
            )
        if not any(succeeded.values()):
            logger.error("东财三级行业资金流两个排行榜请求均失败或无有效数据")
        logger.info(
            "东财三级行业资金流排行榜有效 %d/2，合并后有效 %d 条",
            sum(succeeded.values()),
            len(rows_by_code),
        )

    def _wait_for_successful_ranking(self, delay_seconds, deadline):
        if self._wait_within_deadline(delay_seconds, deadline):
            return True
        logger.error("890 秒总时限不足，放弃后续三级行业排行榜请求")
        return False

    def _wait_within_deadline(self, delay_seconds, deadline):
        if not can_wait_until_deadline(self.clock, delay_seconds, deadline):
            return False
        self.sleep(delay_seconds)
        return True

    # 兼容旧调用方；新的测试和业务代码使用更具体的方法名。
    def _get_with_retry(self, params, *, retry_delays=None, deadline=None):
        retry_delays = retry_delays or iter(self.interval_plan_factory().retry_delays)
        deadline = deadline or self.clock() + MAX_FETCH_DURATION_SECONDS
        return self._fetch_ranking_with_retry(params, retry_delays=retry_delays, deadline=deadline)


def build_ranking_params(sort_order):
    """构造单份三级行业排行榜的查询参数。"""
    return {
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

