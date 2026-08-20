"""
python manage.py fetch_stock_fund_flow

仅在 A 股交易时段内抓取全市场个股当日主力资金流快照，并按 15 分钟刻度写入数据库。
非交易时段直接退出，不发起网络请求，也不写入数据库。

crontab 示例：

    */15 9-15 * * 1-5  cd /path/to/project && /path/to/venv/bin/python manage.py fetch_stock_fund_flow >> /var/log/fundflow/fetch.log 2>&1
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from fundflow.models import StockFundFlowSnapshot
from fundflow.services.aggregation import invalidate_sector_intraday_cache
from fundflow.services.eastmoney_client import EastmoneyClient
from fundflow.services.trading_time import floor_to_15min

# A股交易时段（北京时间），(hour, minute) 元组比较
MORNING_START = (9, 30)
MORNING_END = (11, 30)
AFTERNOON_START = (13, 0)
AFTERNOON_END = (15, 0)


def _within_trading_hours(now_local):
    """判断当前是否处于A股交易时段。仅做工作日+时间段判断，不含法定节假日。"""
    if now_local.weekday() >= 5:  # 5=周六 6=周日
        return False
    current = (now_local.hour, now_local.minute)
    return (MORNING_START <= current <= MORNING_END) or (
        AFTERNOON_START <= current <= AFTERNOON_END
    )


class Command(BaseCommand):
    help = "交易时段内抓取全市场个股当前资金流快照；非交易时段直接退出。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="忽略交易时段检查，强制抓取当前快照（仅用于调试）",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只抓取并打印结果，不写入数据库",
        )

    def handle(self, *args, **options):
        now_local = timezone.localtime(timezone.now())

        if not options["force"] and not _within_trading_hours(now_local):
            self.stdout.write(
                f"{now_local:%Y-%m-%d %H:%M:%S} 不在A股交易时段内，直接退出。"
            )
            return

        self._handle_live_snapshot(now_local, options)

    def _handle_live_snapshot(self, now_local, options):
        snapshot_time = floor_to_15min(now_local)
        trade_date = snapshot_time.date()

        self.stdout.write(
            f"[交易时段] 开始抓取全市场个股资金流，"
            f"快照时间对齐为 {snapshot_time:%Y-%m-%d %H:%M}"
        )

        rows = EastmoneyClient().fetch_all_stock_fund_flow()
        if not rows:
            self.stderr.write(self.style.ERROR("未获取到任何数据（接口失败或返回为空），本次抓取中止。"))
            return

        self.stdout.write(f"共获取 {len(rows)} 只股票的资金流数据，准备写入数据库...")

        if options["dry_run"]:
            for row in rows[:5]:
                self.stdout.write(str(row))
            self.stdout.write(self.style.SUCCESS(f"(dry-run模式，共 {len(rows)} 条，未写入数据库)"))
            return

        objs = [
            StockFundFlowSnapshot(
                stock_code=row["stock_code"],
                stock_name=row["stock_name"],
                market=row["market"],
                trade_date=trade_date,
                snapshot_time=snapshot_time,
                latest_price=row["latest_price"],
                change_pct=row["change_pct"],
                main_net_inflow=row["main_net_inflow"],
                main_net_inflow_ratio=row["main_net_inflow_ratio"],
                super_large_net_inflow=row["super_large_net_inflow"],
                large_net_inflow=row["large_net_inflow"],
                medium_net_inflow=row["medium_net_inflow"],
                small_net_inflow=row["small_net_inflow"],
            )
            for row in rows
        ]

        StockFundFlowSnapshot.objects.bulk_create(
            objs,
            ignore_conflicts=True,
            batch_size=1000,
        )
        invalidate_sector_intraday_cache(trade_date)

        self.stdout.write(
            self.style.SUCCESS(
                f"写入完成：{trade_date} {snapshot_time:%H:%M} 快照，"
                f"尝试写入 {len(objs)} 条记录"
            )
        )
