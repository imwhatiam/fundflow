"""
非交易时段的历史资金流回补逻辑。

交易时段内，`fetch_stock_fund_flow` 命令走的是"批量拉当前这一个时间点"的实时快照逻辑
（详见命令文件本身），逻辑不变。非交易时段运行这个命令时，改走这个模块里的回补逻辑：
用个股分时资金流接口，把"最近一个交易日"的完整分时曲线补齐到数据库——典型场景是服务刚
部署，或者定时任务中断过一段时间，错过了当天盘中的多次15分钟快照。

因为这个接口是"一只股票一次请求"（不像实时快照接口能批量拿全市场），全市场5000+只股票
回补一遍是几千次HTTP请求，比15分钟快照贵得多，所以这里做了两件事控制成本：
1. 回补前先检查这个交易日是否已经"看起来够完整"了，够了就跳过，不重复跑
2. 用小规模并发(默认5个线程)+每个请求间隔小睡一下，降低总耗时的同时避免请求过快
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as dt_time, timedelta

from django.utils import timezone

from fundflow.models import StockFundFlowSnapshot
from fundflow.services.aggregation import invalidate_sector_intraday_cache
from fundflow.services.trading_time import (
    is_15min_trading_clock,
    trading_slots_for_day,
)

logger = logging.getLogger(__name__)

def most_recent_trading_date(now_local):
    """
    粗略推算"最近一个交易日"的日期。只跳过周末，不处理法定节假日——如需精确到交易日历，
    可以接入 `chinese_calendar` 库替换这里的 weekday 判断（跟 fetch_stock_fund_flow 里
    `_within_trading_hours` 的简化方式保持一致）。

    - 如果现在是工作日，且已经过了开盘时间(9:30)，最近交易日就是今天
      （哪怕现在是午休或者还没收盘，回补当前已有的部分曲线也是有意义的）
    - 否则（工作日开盘前，或者周末）就往前找最近一个工作日
    """
    d = now_local.date()
    if now_local.weekday() < 5 and now_local.time() >= dt_time(9, 30):
        return d

    target = d - timedelta(days=1)
    while target.weekday() >= 5:
        target -= timedelta(days=1)
    return target


def is_already_backfilled(trade_date):
    """仅当完整交易日的全部标准刻度都已入库时才视为回补完成。"""
    expected_slots = set(trading_slots_for_day(trade_date))
    actual_slots = set(
        StockFundFlowSnapshot.objects.filter(
            trade_date=trade_date,
            snapshot_time__in=expected_slots,
        )
        .values_list("snapshot_time", flat=True)
        .distinct()
    )
    return expected_slots.issubset(actual_slots)


def _downsample_to_15min(points):
    """只保留交易时段内的标准15分钟刻度，与实时快照粒度保持一致。"""
    result = []
    for p in points:
        try:
            hour_str, minute_str = p["time"].split(":")
            if is_15min_trading_clock(int(hour_str), int(minute_str)):
                result.append(p)
        except (KeyError, ValueError):
            continue
    return result


def backfill_most_recent_trading_day(
    client, trade_date, stock_universe, sleep_interval=0.15, max_workers=5, progress_cb=None
):
    """
    对给定的股票列表逐只请求分时资金流历史曲线，下采样到15分钟粒度后批量写入数据库。

    参数：
        client: EastmoneyClient 实例
        trade_date: 要回补的交易日 (date)
        stock_universe: list[{"stock_code", "market", "stock_name"}]
        sleep_interval: 每个请求线程自己的节流间隔（秒）
        max_workers: 并发线程数，别设太大，这是未公开接口，保持克制
        progress_cb: 可选，签名 (done, total, success, fail) -> None，用于命令行打印进度

    返回：(success_count, fail_count, rows_written)
    """
    base_dt = timezone.make_aware(datetime.combine(trade_date, dt_time(0, 0)))

    def _fetch_one(stock):
        raw_points = client.fetch_stock_intraday_history(stock["stock_code"], stock["market"])
        time.sleep(sleep_interval)  # 在worker线程内节流，而不是主线程里对已完成的future节流
        return stock, _downsample_to_15min(raw_points)

    all_objs = []
    success_count, fail_count = 0, 0
    total = len(stock_universe)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, s): s for s in stock_universe}
        done = 0
        for future in as_completed(futures):
            stock = futures[future]
            done += 1
            try:
                stock, points = future.result()
            except Exception as exc:  # noqa: BLE001 - 单只股票请求异常不能影响整批回补
                logger.warning("回补 %s 失败: %s", stock["stock_code"], exc)
                points = []

            if not points:
                fail_count += 1
            else:
                success_count += 1
                for p in points:
                    hour_str, minute_str = p["time"].split(":")
                    snapshot_time = base_dt.replace(hour=int(hour_str), minute=int(minute_str))
                    all_objs.append(
                        StockFundFlowSnapshot(
                            stock_code=stock["stock_code"],
                            stock_name=stock.get("stock_name", ""),
                            market=stock["market"],
                            trade_date=trade_date,
                            snapshot_time=snapshot_time,
                            main_net_inflow=p["main_net_inflow"],
                            super_large_net_inflow=p.get("super_large_net_inflow"),
                            large_net_inflow=p.get("large_net_inflow"),
                            medium_net_inflow=p.get("medium_net_inflow"),
                            small_net_inflow=p.get("small_net_inflow"),
                        )
                    )

            if progress_cb and (done % 500 == 0 or done == total):
                progress_cb(done, total, success_count, fail_count)

    written = 0
    if all_objs:
        # ignore_conflicts=True：如果这个时间点这只股票已经有数据了（比如早盘交易时段的
        # 实时快照已经抓过），直接跳过，不会覆盖已有数据，也不会因为唯一约束冲突报错。
        StockFundFlowSnapshot.objects.bulk_create(all_objs, ignore_conflicts=True, batch_size=2000)
        written = len(all_objs)
        invalidate_sector_intraday_cache(trade_date)

    return success_count, fail_count, written
