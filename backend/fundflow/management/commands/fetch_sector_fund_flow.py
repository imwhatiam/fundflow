"""抓取东方财富行业板块资金流快照。"""

from datetime import datetime, time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from fundflow.models import (
    EastmoneySectorFundFlowSnapshot,
    EastmoneySectorFundFlowSnapshotStatus,
)
from fundflow.services.aggregation import invalidate_sector_intraday_cache
from fundflow.services.eastmoney_client import EastmoneyClient
from fundflow.services.trading_calendar import (
    is_a_share_trading_day,
    previous_a_share_trading_day,
)
from fundflow.services.trading_time import floor_to_15min, trading_slots_for_day

MORNING_START = (9, 30)
MORNING_END = (11, 30)
AFTERNOON_START = (13, 0)
AFTERNOON_END = (15, 0)


def _within_trading_hours(now_local):
    """判断当前是否处于 A 股交易时段（含法定节假日过滤）。"""
    if not is_a_share_trading_day(now_local.date()):
        return False
    current = (now_local.hour, now_local.minute)
    return (MORNING_START <= current <= MORNING_END) or (
        AFTERNOON_START <= current <= AFTERNOON_END
    )


def _fallback_latest_snapshot_time(now_local):
    """为没有上游行情时间的响应推断最近可用的标准快照时间。"""
    current = now_local.timetz().replace(tzinfo=None)
    if not is_a_share_trading_day(now_local.date()):
        trade_date = previous_a_share_trading_day(now_local.date())
        return timezone.make_aware(datetime.combine(trade_date, time(15, 0)))

    if current < time(9, 30):
        trade_date = previous_a_share_trading_day(now_local.date())
        return timezone.make_aware(datetime.combine(trade_date, time(15, 0)))
    if current < time(13, 0):
        return timezone.make_aware(datetime.combine(now_local.date(), time(11, 30)))
    return timezone.make_aware(datetime.combine(now_local.date(), time(15, 0)))


def _align_to_latest_trading_slot(value):
    """将上游行情时间压到其所在交易日已经结束的最近合法刻度。"""
    if not is_a_share_trading_day(value.date()):
        return _fallback_latest_snapshot_time(value)

    elapsed_slots = [slot for slot in trading_slots_for_day(value.date()) if slot <= value]
    if elapsed_slots:
        return elapsed_slots[-1]
    return _fallback_latest_snapshot_time(value)


def _latest_snapshot_time_from_source_rows(rows, fallback_now_local):
    """优先使用东财 f124 行情时间，缺失时才按本地时间回退。"""
    source_times = []
    tz = timezone.get_current_timezone()
    for row in rows:
        try:
            timestamp = float(row.get("source_timestamp"))
            # 东财当前返回秒级 Unix 时间戳；兼容可能出现的毫秒级值。
            if timestamp >= 10_000_000_000:
                timestamp /= 1000
            source_times.append(datetime.fromtimestamp(timestamp, tz=tz))
        except (OSError, OverflowError, TypeError, ValueError):
            continue

    if source_times:
        return _align_to_latest_trading_slot(max(source_times))
    return _fallback_latest_snapshot_time(fallback_now_local)


def _model_values(row):
    """移除仅用于确定快照时刻的上游临时字段。"""
    return {key: value for key, value in row.items() if key != "source_timestamp"}


class Command(BaseCommand):
    help = "交易时段内抓取东方财富行业板块资金流快照；非交易时段默认直接退出。"

    def create_parser(self, prog_name, subcommand, **kwargs):
        # Django 自带 --force-color；禁用参数缩写，避免已删除的 --force 被误解析为它。
        kwargs["allow_abbrev"] = False
        return super().create_parser(prog_name, subcommand, **kwargs)

    def add_arguments(self, parser):
        parser.add_argument(
            "--latest",
            action="store_true",
            help="非交易时段抓取东方财富最近可用行业快照，并按上游时间写入",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只抓取并打印结果，不写入数据库",
        )

    def handle(self, *args, **options):
        now_local = timezone.localtime(timezone.now())
        within_trading_hours = _within_trading_hours(now_local)
        latest_mode = options["latest"] and not within_trading_hours

        if not within_trading_hours and not latest_mode:
            self.stdout.write(f"{now_local:%Y-%m-%d %H:%M:%S} 不在A股交易时段内，直接退出。")
            return

        if latest_mode:
            self.stdout.write("[非交易时段] 开始抓取东方财富最近可用行业资金流快照...")
        else:
            snapshot_time = floor_to_15min(now_local)
            self.stdout.write(
                "[交易时段] 开始抓取东方财富行业资金流，"
                f"快照时间对齐为 {snapshot_time:%Y-%m-%d %H:%M}"
            )

        client = EastmoneyClient()
        result = client.fetch_sector_fund_flow_leaders()
        rows = result.rows
        if not rows:
            self.stderr.write(self.style.ERROR("未获取到任何数据（接口失败或返回为空），本次抓取中止。"))
            return

        if latest_mode:
            snapshot_time = _latest_snapshot_time_from_source_rows(rows, now_local)
            self.stdout.write(
                "[非交易时段] 已按东方财富最近可用行情时间对齐为 "
                f"{snapshot_time:%Y-%m-%d %H:%M}"
            )

        trade_date = snapshot_time.date()
        self.stdout.write(f"共获取 {len(rows)} 个行业板块的资金流数据，准备写入数据库...")
        if options["dry_run"]:
            for row in rows[:5]:
                self.stdout.write(str(_model_values(row)))
            self.stdout.write(self.style.SUCCESS(f"(dry-run模式，共 {len(rows)} 条，未写入数据库)"))
            return

        snapshots = [
            EastmoneySectorFundFlowSnapshot(
                trade_date=trade_date,
                snapshot_time=snapshot_time,
                **_model_values(row),
            )
            for row in rows
        ]
        with transaction.atomic():
            EastmoneySectorFundFlowSnapshot.objects.bulk_create(
                snapshots,
                update_conflicts=True,
                update_fields=[
                    "trade_date",
                    "sector_name",
                    "latest_index",
                    "change_pct",
                    "main_net_inflow",
                    "main_net_inflow_ratio",
                    "super_large_net_inflow",
                    "large_net_inflow",
                    "medium_net_inflow",
                    "small_net_inflow",
                ],
                unique_fields=["sector_code", "snapshot_time"],
                batch_size=500,
            )
            EastmoneySectorFundFlowSnapshotStatus.objects.update_or_create(
                snapshot_time=snapshot_time,
                defaults={
                    "trade_date": trade_date,
                    "inflow_succeeded": result.inflow_succeeded,
                    "outflow_succeeded": result.outflow_succeeded,
                },
            )
        if not (result.inflow_succeeded and result.outflow_succeeded):
            self.stderr.write(
                self.style.WARNING(
                    "本次快照仅获得部分排行榜数据；API 将标记为 stale，"
                    "并在缺失方向回退到上一个时间刻度。"
                )
            )
        invalidate_sector_intraday_cache(trade_date)
        self.stdout.write(
            self.style.SUCCESS(
                f"写入完成：{trade_date} {snapshot_time:%H:%M} 快照，"
                f"尝试写入 {len(snapshots)} 条记录"
            )
        )
