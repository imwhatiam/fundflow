"""
python manage.py fetch_stock_fund_flow

抓取全市场个股当日主力资金流快照，按5分钟对齐写入数据库。
设计为配合 crontab 每5分钟执行一次，命令本身是幂等的：
同一个5分钟时间点重复执行不会产生重复数据（依赖数据库唯一约束 + ignore_conflicts）。

crontab 示例（交易日 9:25-15:05 每5分钟跑一次，具体是否在交易时段由命令内部再判断一次）：

    */5 9-15 * * 1-5  cd /path/to/project && /path/to/venv/bin/python manage.py fetch_stock_fund_flow >> /var/log/fundflow/fetch.log 2>&1
"""

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from fundflow.models import StockFundFlowSnapshot
from fundflow.services.eastmoney_client import EastmoneyClient

logger = logging.getLogger(__name__)

# A股交易时段（北京时间），(hour, minute) 元组比较
MORNING_START = (9, 30)
MORNING_END = (11, 30)
AFTERNOON_START = (13, 0)
AFTERNOON_END = (15, 0)


def _within_trading_hours(now_local):
    """判断当前是否处于A股交易时段。仅做工作日+时间段判断，不含法定节假日，
    如需精确到交易日历，可接入 `chinese_calendar` 库替换这里的 weekday 判断。"""
    if now_local.weekday() >= 5:  # 5=周六 6=周日
        return False
    t = (now_local.hour, now_local.minute)
    return (MORNING_START <= t <= MORNING_END) or (AFTERNOON_START <= t <= AFTERNOON_END)


def _floor_to_5min(dt):
    """把时间向下取整到最近的5分钟刻度，避免cron实际触发时间有几秒漂移导致
    同一个"5分钟窗口"被记成两个不同的 snapshot_time。"""
    minute = (dt.minute // 5) * 5
    return dt.replace(minute=minute, second=0, microsecond=0)


class Command(BaseCommand):
    help = "抓取全市场个股当日主力资金流快照，按5分钟对齐写入数据库（配合 crontab 每5分钟执行）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="忽略交易时段检查，强制抓取一次（调试用）",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只抓取并打印前几条结果，不写入数据库",
        )

    def handle(self, *args, **options):
        now_local = timezone.localtime(timezone.now())

        if not options["force"] and not _within_trading_hours(now_local):
            self.stdout.write(
                self.style.WARNING(
                    f"{now_local:%Y-%m-%d %H:%M:%S} 不在A股交易时段内，跳过本次抓取。"
                    "（调试可加 --force 强制执行）"
                )
            )
            return

        snapshot_time = _floor_to_5min(now_local)
        trade_date = snapshot_time.date()

        self.stdout.write(f"开始抓取全市场个股资金流，快照时间对齐为 {snapshot_time:%Y-%m-%d %H:%M}")

        client = EastmoneyClient()
        rows = client.fetch_all_stock_fund_flow()

        if not rows:
            self.stderr.write(self.style.ERROR("未获取到任何数据（接口失败或返回为空），本次抓取中止。"))
            return

        self.stdout.write(f"共获取 {len(rows)} 只股票的资金流数据，准备写入数据库...")

        if options["dry_run"]:
            for r in rows[:5]:
                self.stdout.write(str(r))
            self.stdout.write(self.style.SUCCESS(f"(dry-run模式，共 {len(rows)} 条，未写入数据库)"))
            return

        objs = [
            StockFundFlowSnapshot(
                stock_code=r["stock_code"],
                stock_name=r["stock_name"],
                market=r["market"],
                trade_date=trade_date,
                snapshot_time=snapshot_time,
                latest_price=r["latest_price"],
                change_pct=r["change_pct"],
                main_net_inflow=r["main_net_inflow"],
                main_net_inflow_ratio=r["main_net_inflow_ratio"],
                super_large_net_inflow=r["super_large_net_inflow"],
                large_net_inflow=r["large_net_inflow"],
                medium_net_inflow=r["medium_net_inflow"],
                small_net_inflow=r["small_net_inflow"],
            )
            for r in rows
        ]

        # ignore_conflicts=True：命中唯一约束(stock_code, snapshot_time)的行直接跳过，
        # 这样即使 crontab 因为服务重启等原因在同一个5分钟窗口内被触发两次，也不会报错或产生脏数据。
        StockFundFlowSnapshot.objects.bulk_create(objs, ignore_conflicts=True, batch_size=1000)

        self.stdout.write(
            self.style.SUCCESS(
                f"写入完成：{trade_date} {snapshot_time:%H:%M} 快照，尝试写入 {len(objs)} 条记录"
            )
        )
