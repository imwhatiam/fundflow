"""抓取东方财富三级行业资金流快照。"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from fundflow.services.eastmoney_client import EastmoneyClient
from fundflow.services.snapshot_collection import collect_sector_snapshot
from fundflow.services.snapshot_time import is_within_trading_hours
from fundflow.services.snapshot_writer import model_values, save_sector_snapshot
from fundflow.services.trading_time import floor_to_15min


class Command(BaseCommand):
    help = "交易时段内抓取东方财富三级行业资金流快照；非交易时段默认直接退出。"

    def create_parser(self, prog_name, subcommand, **kwargs):
        # Django 自带 --force-color；禁用参数缩写，避免已删除的 --force 被误解析为它。
        kwargs["allow_abbrev"] = False
        return super().create_parser(prog_name, subcommand, **kwargs)

    def add_arguments(self, parser):
        parser.add_argument(
            "--latest",
            action="store_true",
            help="非交易时段抓取东方财富最近可用三级行业快照，并按上游时间写入",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只抓取并打印结果，不写入数据库",
        )

    def handle(self, *args, **options):
        now_local = timezone.localtime(timezone.now())
        within_trading_hours = is_within_trading_hours(now_local)
        latest_mode = options["latest"] and not within_trading_hours

        if not within_trading_hours and not latest_mode:
            self.stdout.write(f"{now_local:%Y-%m-%d %H:%M:%S} 不在A股交易时段内，直接退出。")
            return

        self._write_start_message(now_local, latest_mode)
        collected = collect_sector_snapshot(
            now_local=now_local,
            latest_mode=latest_mode,
            fetcher=EastmoneyClient(),
        )
        fetch_result = collected.fetch_result
        if not fetch_result.rows:
            self.stderr.write(self.style.ERROR("未获取到任何数据（接口失败或返回为空），本次抓取中止。"))
            return

        self._write_snapshot_time_message(collected.snapshot_time, latest_mode)
        self.stdout.write(f"共获取 {len(fetch_result.rows)} 个三级行业的资金流数据，准备写入数据库...")
        if options["dry_run"]:
            self._write_dry_run_result(fetch_result.rows)
            return

        saved = save_sector_snapshot(
            snapshot_time=collected.snapshot_time,
            fetch_result=fetch_result,
        )
        self._write_save_result(collected.snapshot_time, fetch_result, saved.row_count)

    def _write_start_message(self, now_local, latest_mode):
        if latest_mode:
            self.stdout.write("[非交易时段] 开始抓取东方财富最近可用三级行业资金流快照...")
            return
        self.stdout.write(
            "[交易时段] 开始抓取东方财富三级行业资金流，"
            f"快照时间对齐为 {floor_to_15min(now_local):%Y-%m-%d %H:%M}"
        )

    def _write_snapshot_time_message(self, snapshot_time, latest_mode):
        if not latest_mode:
            return
        self.stdout.write(
            "[非交易时段] 已按东方财富最近可用行情时间对齐为 "
            f"{snapshot_time:%Y-%m-%d %H:%M}"
        )

    def _write_dry_run_result(self, rows):
        for row in rows[:5]:
            self.stdout.write(str(model_values(row)))
        self.stdout.write(self.style.SUCCESS(f"(dry-run模式，共 {len(rows)} 条，未写入数据库)"))

    def _write_save_result(self, snapshot_time, fetch_result, row_count):
        if not (fetch_result.inflow_succeeded and fetch_result.outflow_succeeded):
            self.stderr.write(
                self.style.WARNING(
                    "本次快照仅获得部分排行榜数据；API 将标记为 stale，"
                    "并在缺失方向回退到上一个时间刻度。"
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"写入完成：{snapshot_time.date()} {snapshot_time:%H:%M} 快照，"
                f"尝试写入 {row_count} 条记录"
            )
        )
