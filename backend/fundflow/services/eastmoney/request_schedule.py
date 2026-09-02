"""三级行业请求的间隔计划和总时限判断。"""

import random

from .constants import (
    MAX_REQUEST_INTERVAL_TOTAL_SECONDS,
    MIN_RETRY_INTERVAL_SECONDS,
    RETRY_INTERVAL_COUNT,
    SUCCESSFUL_RANKING_INTERVAL_SECONDS,
)
from .types import RequestIntervalPlan


def prepare_interval_plan(random_source=None):
    """在首个请求前生成十个互不相同、预算内的重试间隔。

    两个排行榜各有五次重试。120 秒的跨榜单成功间隔固定，因此十个随机
    重试间隔与它合计不得超过 700 秒。候选范围刻意较小，保证每次重试都
    至少等待 45 秒，同时让最坏情况下的请求间隔始终处于预算内。
    """
    random_source = random_source or random
    retry_delay_candidates = range(
        MIN_RETRY_INTERVAL_SECONDS,
        MIN_RETRY_INTERVAL_SECONDS + RETRY_INTERVAL_COUNT,
    )
    retry_delays = tuple(random_source.sample(retry_delay_candidates, RETRY_INTERVAL_COUNT))
    plan = RequestIntervalPlan(
        retry_delays=retry_delays,
        successful_ranking_delay=SUCCESSFUL_RANKING_INTERVAL_SECONDS,
    )
    validate_interval_plan(plan)
    return plan


def validate_interval_plan(plan):
    """验证请求间隔规则；无效计划立即暴露为程序错误。"""
    if len(plan.retry_delays) != RETRY_INTERVAL_COUNT:
        raise ValueError("重试间隔数量必须覆盖两个排行榜各五次重试")
    if min(plan.retry_delays) < MIN_RETRY_INTERVAL_SECONDS:
        raise ValueError("每个重试间隔不得小于 45 秒")
    if len(set(plan.retry_delays)) != len(plan.retry_delays):
        raise ValueError("每个重试间隔必须不同")
    if plan.successful_ranking_delay != SUCCESSFUL_RANKING_INTERVAL_SECONDS:
        raise ValueError("成功跨榜单间隔必须为 120 秒")
    if plan.successful_ranking_delay in plan.retry_delays:
        raise ValueError("成功跨榜单间隔不得与重试间隔重复")
    if plan.total_seconds > MAX_REQUEST_INTERVAL_TOTAL_SECONDS:
        raise ValueError("所有计划请求间隔总和不得超过 700 秒")


def can_wait_until_deadline(clock, delay_seconds, deadline):
    """判断完整等待指定秒数后是否仍未超出本轮抓取 deadline。"""
    return deadline - clock() >= delay_seconds
