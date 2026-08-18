"""
python manage.py sync_sectors

同步板块（行业/概念）列表及其成分股映射关系。这是"低频"任务——板块划分不常变化，
建议一天跑一次（比如收盘后），不要跟 fetch_stock_fund_flow 一样每5分钟跑。

数据来源：
- industry（行业板块）：读取本地 CSV 文件（默认在 backend 的上一级目录，即
  项目根目录下的"沪深京A股.csv"），按"所属行业"列分组，不再请求东财板块接口。
- concept（概念板块）：仍然请求东财板块列表 + 成分股接口（东财没有把"概念"信息放进
  这份CSV导出里，所以概念板块的数据源没变）。

板块级别的资金流曲线不需要单独抓取/存储：前端请求板块数据时，后端拿这张表里的
"板块->成分股"关系，去 StockFundFlowSnapshot 表按时间点分组求和，实时聚合出来。

crontab 示例（每天 15:30 跑一次，交易日收盘后）：

    30 15 * * 1-5  cd /path/to/backend && /path/to/venv/bin/python manage.py sync_sectors >> /var/log/fundflow/sync_sectors.log 2>&1

如果"沪深京A股.csv"是手动/定期更新的（比如每天从行情软件重新导出一份覆盖旧文件），
直接照常跑这个命令即可，会用文件里的最新数据重建行业板块映射。
"""

import logging
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fundflow.models import Sector, SectorConstituent
from fundflow.services.csv_import import industry_sector_code, parse_industry_csv
from fundflow.services.eastmoney_client import EastmoneyClient

logger = logging.getLogger(__name__)

DEFAULT_CSV_FILENAME = "沪深京A股.csv"


class Command(BaseCommand):
    help = (
        "同步板块列表及成分股映射（低频任务，建议每天执行一次）。"
        "行业板块从本地CSV文件读取，概念板块仍走东财接口。"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--category",
            choices=["industry", "concept", "all"],
            default="industry",
            help="同步哪类板块。concept(概念板块)走东财接口，有几百个、耗时长；"
            "industry(行业板块)默认从本地CSV读取，很快。",
        )
        parser.add_argument(
            "--csv-path",
            default=None,
            help="行业板块CSV文件路径。不指定时默认使用项目根目录（backend的上一级目录）下的"
            f"「{DEFAULT_CSV_FILENAME}」。",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.3,
            help="(仅concept) 抓取每个板块成分股之间的间隔秒数，避免请求过快被限流，默认0.3秒",
        )

    def handle(self, *args, **options):
        categories = (
            ["industry", "concept"] if options["category"] == "all" else [options["category"]]
        )

        for category in categories:
            if category == "industry":
                self._sync_industry_from_csv(options["csv_path"])
            else:
                client = EastmoneyClient()
                self._sync_concept_from_api(client, options["sleep"])

    # ------------------------------------------------------------------
    # 行业板块：从本地 CSV 文件读取
    # ------------------------------------------------------------------

    def _resolve_csv_path(self, csv_path_option):
        if csv_path_option:
            return Path(csv_path_option)
        # backend/ 的上一级目录，即项目根目录（跟 backend/、frontend/ 同级）
        return Path(settings.BASE_DIR).parent / DEFAULT_CSV_FILENAME

    def _sync_industry_from_csv(self, csv_path_option):
        csv_path = self._resolve_csv_path(csv_path_option)

        self.stdout.write(f"开始从CSV同步行业板块: {csv_path}")

        if not csv_path.exists():
            raise CommandError(
                f"找不到CSV文件: {csv_path}\n"
                f"请确认文件存在，或用 --csv-path 显式指定路径。"
            )

        try:
            grouped = parse_industry_csv(csv_path)
        except ValueError as exc:
            raise CommandError(f"解析CSV文件失败: {exc}") from exc

        if not grouped:
            raise CommandError("CSV文件解析出的行业数据为空，请检查文件内容是否正确。")

        sector_count, constituent_count = 0, 0

        for industry_name, stocks in grouped.items():
            code = industry_sector_code(industry_name)

            # 同一行业下同一只股票在文件里理论上不会重复，这里按 stock_code 去重防御一下
            unique_stocks = list({s["stock_code"]: s for s in stocks}.values())

            with transaction.atomic():
                sector, _ = Sector.objects.update_or_create(
                    code=code, defaults={"name": industry_name, "category": "industry"}
                )
                SectorConstituent.objects.filter(sector=sector).delete()
                SectorConstituent.objects.bulk_create(
                    [
                        SectorConstituent(
                            sector=sector, stock_code=s["stock_code"], stock_name=s["stock_name"]
                        )
                        for s in unique_stocks
                    ]
                )

            sector_count += 1
            constituent_count += len(unique_stocks)

        self.stdout.write(
            self.style.SUCCESS(
                f"行业板块同步完成：共 {sector_count} 个行业，{constituent_count} 条成分股映射"
                f"（数据源: {csv_path.name}）"
            )
        )

    # ------------------------------------------------------------------
    # 概念板块：沿用东财接口（这份CSV里没有概念板块信息）
    # ------------------------------------------------------------------

    def _sync_concept_from_api(self, client, sleep_interval):
        self.stdout.write("开始同步概念板块列表(东财接口)...")

        sector_list = client.fetch_sector_list(category="concept")
        if not sector_list:
            self.stderr.write(self.style.ERROR("概念板块列表获取失败，跳过。"))
            return

        self.stdout.write(f"概念板块共 {len(sector_list)} 个，开始逐个同步成分股（间隔{sleep_interval}秒/个）...")

        ok_count, fail_count = 0, 0
        for i, sector_info in enumerate(sector_list, start=1):
            code, name = sector_info["code"], sector_info["name"]

            constituents = client.fetch_sector_constituents(code)
            if not constituents:
                self.stdout.write(
                    self.style.WARNING(f"  [{i}/{len(sector_list)}] {name}({code}) 成分股为空，跳过")
                )
                fail_count += 1
                time.sleep(sleep_interval)
                continue

            with transaction.atomic():
                sector, _ = Sector.objects.update_or_create(
                    code=code, defaults={"name": name, "category": "concept"}
                )
                SectorConstituent.objects.filter(sector=sector).delete()
                SectorConstituent.objects.bulk_create(
                    [
                        SectorConstituent(
                            sector=sector,
                            stock_code=c["stock_code"],
                            stock_name=c.get("stock_name", ""),
                        )
                        for c in constituents
                    ]
                )

            ok_count += 1
            if i % 10 == 0 or i == len(sector_list):
                self.stdout.write(f"  进度 {i}/{len(sector_list)}（成功{ok_count} 失败{fail_count}）")

            time.sleep(sleep_interval)

        self.stdout.write(
            self.style.SUCCESS(f"概念板块同步完成：成功 {ok_count} 个，失败/为空 {fail_count} 个")
        )
