"""抓取开盘啦板块资金流快照。"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from kaipanla.services.ranking_fetcher import KaipanlaRankingFetcher
from kaipanla.services.snapshot_collection import collect_kaipanla_snapshot
from kaipanla.services.snapshot_time import is_within_trading_hours
from kaipanla.services.snapshot_writer import model_values, save_kaipanla_snapshot
from kaipanla.services.trading_time import floor_to_snapshot_interval


class Command(BaseCommand):
    help = "交易时段内抓取开盘啦板块资金流快照；非交易时段默认直接退出。"

    def create_parser(self, prog_name, subcommand, **kwargs):
        kwargs["allow_abbrev"] = False
        return super().create_parser(prog_name, subcommand, **kwargs)

    def add_arguments(self, parser):
        parser.add_argument(
            "--latest",
            action="store_true",
            help="非交易时段抓取开盘啦最近可用板块快照，并按上游时间写入",
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
        collected = collect_kaipanla_snapshot(
            now_local=now_local,
            latest_mode=latest_mode,
            fetcher=KaipanlaRankingFetcher(),
        )
        fetch_result = collected.fetch_result
        if not fetch_result.rows:
            self.stderr.write(self.style.ERROR("未获取到任何数据（接口失败或返回为空），本次抓取中止。"))
            return

        self._write_snapshot_time_message(collected.snapshot_time, latest_mode)
        self.stdout.write(f"共获取 {len(fetch_result.rows)} 个板块的资金流数据，准备写入数据库...")
        if options["dry_run"]:
            self._write_dry_run_result(fetch_result.rows)
            return

        saved = save_kaipanla_snapshot(
            snapshot_time=collected.snapshot_time,
            fetch_result=fetch_result,
        )
        self._write_save_result(collected.snapshot_time, fetch_result, saved.row_count)

    def _write_start_message(self, now_local, latest_mode):
        if latest_mode:
            self.stdout.write("[非交易时段] 开始抓取开盘啦最近可用板块资金流快照...")
            return
        self.stdout.write(
            "[交易时段] 开始抓取开盘啦板块资金流，"
            f"快照时间对齐为 {floor_to_snapshot_interval(now_local):%Y-%m-%d %H:%M}"
        )

    def _write_snapshot_time_message(self, snapshot_time, latest_mode):
        if not latest_mode:
            return
        self.stdout.write(
            "[非交易时段] 已按开盘啦最近可用行情时间对齐为 "
            f"{snapshot_time:%Y-%m-%d %H:%M}"
        )

    def _write_dry_run_result(self, rows):
        for row in rows[:5]:
            self.stdout.write(str(model_values(row)))
        self.stdout.write(self.style.SUCCESS(f"(dry-run模式，共 {len(rows)} 条，未写入数据库)"))

    def _write_save_result(self, snapshot_time, fetch_result, row_count):
        if not fetch_result.fetch_succeeded:
            self.stderr.write(
                self.style.WARNING(
                    "本次快照抓取失败；该刻度未写入任何数据，前端将沿用上一个有数据的刻度。"
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"写入完成：{snapshot_time.date()} {snapshot_time:%H:%M} 快照，"
                f"尝试写入 {row_count} 条记录"
            )
        )
