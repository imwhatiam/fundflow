"""
python manage.py sync_sectors

同步行业板块及成分股映射关系（数据源：本地 CSV 文件"沪深京A股.csv"，按"所属行业"列分组）。
这是"低频"任务——板块划分不常变化，建议一天跑一次（比如收盘后），不要跟
fetch_stock_fund_flow 一样每15分钟跑。

板块级别的资金流曲线不需要单独抓取/存储：前端请求板块数据时，后端拿这张表里的
"板块->成分股"关系，去 StockFundFlowSnapshot 表按时间点分组求和，实时聚合出来。

crontab 示例（每天 15:30 跑一次，交易日收盘后）：

    30 15 * * 1-5  cd /path/to/backend && /path/to/venv/bin/python manage.py sync_sectors >> /var/log/fundflow/sync_sectors.log 2>&1

如果"沪深京A股.csv"是手动/定期更新的（比如每天从行情软件重新导出一份覆盖旧文件），
直接照常跑这个命令即可，会用文件里的最新数据重建行业板块映射。
"""

import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fundflow.models import Sector, SectorConstituent
from fundflow.services.csv_import import industry_sector_code, parse_industry_csv

logger = logging.getLogger(__name__)

DEFAULT_CSV_FILENAME = "沪深京A股.csv"


class Command(BaseCommand):
    help = "同步行业板块及成分股映射（数据源：本地CSV文件，低频任务，建议每天执行一次）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv-path",
            default=None,
            help="CSV文件路径。不指定时默认使用项目根目录（backend的上一级目录）下的"
            f"「{DEFAULT_CSV_FILENAME}」。",
        )

    def handle(self, *args, **options):
        csv_path = self._resolve_csv_path(options["csv_path"])

        self.stdout.write(f"开始从CSV同步行业板块: {csv_path}")

        if not csv_path.exists():
            raise CommandError(
                f"找不到CSV文件: {csv_path}\n"
                f"请确认文件存在（与 backend/ 同级目录），或用 --csv-path 显式指定路径。"
            )

        try:
            grouped = parse_industry_csv(csv_path)
        except ValueError as exc:
            raise CommandError(f"解析CSV文件失败: {exc}") from exc

        if not grouped:
            raise CommandError("CSV文件解析出的行业数据为空，请检查文件内容是否正确。")

        sector_count, constituent_count = 0, 0
        synced_codes = set()

        for industry_name, stocks in grouped.items():
            code = industry_sector_code(industry_name)
            synced_codes.add(code)

            # 同一行业下同一只股票在文件里理论上不会重复，这里按 stock_code 去重防御一下
            unique_stocks = list({s["stock_code"]: s for s in stocks}.values())

            with transaction.atomic():
                sector, _ = Sector.objects.update_or_create(
                    code=code, defaults={"name": industry_name}
                )
                # 每次同步前清空旧成分股，再整体写入最新的，避免"调出板块"的旧股票残留
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

        # 清理这次同步里没有出现过的旧板块（比如CSV数据源的行业分类发生了变化），
        # 级联删除会自动清掉对应的 SectorConstituent，不会留下孤儿数据。
        stale_qs = Sector.objects.exclude(code__in=synced_codes)
        stale_count = stale_qs.count()
        if stale_count:
            stale_qs.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"行业板块同步完成：共 {sector_count} 个行业，{constituent_count} 条成分股映射"
                f"（数据源: {csv_path.name}），清理掉 {stale_count} 个失效的旧板块"
            )
        )

    def _resolve_csv_path(self, csv_path_option):
        if csv_path_option:
            return Path(csv_path_option)
        # backend/ 的上一级目录，即项目根目录（跟 backend/、frontend/ 同级）
        return Path(settings.BASE_DIR).parent / DEFAULT_CSV_FILENAME
