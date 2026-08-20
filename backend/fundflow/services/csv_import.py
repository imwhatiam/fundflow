"""
从本地导出的"沪深京A股.csv"解析个股所属行业，用于离线构建"行业板块 -> 成分股"映射，
替代原来实时请求东财板块列表/成分股接口的方式。

文件格式（实测样本）：
- 编码：UTF-16（带 BOM），典型的行情软件导出格式
- 分隔符：制表符 \\t
- 大部分字段用双引号包裹；"代码"字段前缀了一个英文单引号（Excel防止长数字被截断的常见技巧，
  如 '300189），需要去掉
- 关键列：代码、名称、所属行业（其余列本模块不关心）
"""

import csv
import hashlib
import io
import logging

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"代码", "名称", "所属行业"}

# CSV导出软件对"暂无行业分类"的股票（常见于北交所新股、定向转让品种等）会填这类占位符，
# 不是真实的行业名称，需要当作缺失值过滤掉，否则会生成一个名为"--"的假板块。
MISSING_INDUSTRY_PLACEHOLDERS = {"--", "-", "无", "未知", "N/A", ""}


def industry_sector_code(industry_name: str) -> str:
    """
    根据行业名称生成稳定、确定性的板块代码。

    CSV数据源里没有像东财 BK0490 那样的官方板块代码，这里用行业名称的哈希值生成一个
    固定代码——同一个行业名称永远映射到同一个 code，重复导入/更新不会产生重复板块记录，
    也不会跟东财接口同步出来的概念板块 code（真实 BKxxxx）冲突。
    """
    digest = hashlib.md5(industry_name.encode("utf-8")).hexdigest()[:10]
    return f"CSV{digest}"


def parse_industry_csv(path):
    """
    解析行情软件导出的个股列表CSV，按"所属行业"分组。

    返回：dict[行业名称, list[{"stock_code": str, "stock_name": str}]]
    出现编码错误、缺少必需列等问题时抛出 ValueError，调用方（management command）负责友好提示。
    """
    try:
        with open(path, encoding="utf-16") as f:
            content = f.read()
    except UnicodeError as exc:
        raise ValueError(
            f"文件编码不是预期的 UTF-16（带BOM），解析失败: {exc}。"
            "如果文件是用 Excel 另存的，注意选择「Unicode文本」或原始导出格式，不要另存为 UTF-8 CSV。"
        ) from exc

    reader = csv.DictReader(io.StringIO(content), delimiter="\t")

    if reader.fieldnames is None:
        raise ValueError(f"CSV文件为空或无法解析出表头: {path}")

    # 表头第一个字段常常带 BOM 字符，统一清理后再校验
    clean_fieldnames = {name.lstrip("\ufeff").strip() for name in reader.fieldnames}
    missing = REQUIRED_COLUMNS - clean_fieldnames
    if missing:
        raise ValueError(
            f"CSV文件缺少必需列: {missing}；实际解析到的列: {sorted(clean_fieldnames)}"
        )

    grouped = {}
    skipped = 0
    total = 0

    for raw_row in reader:
        total += 1
        row = {(k.lstrip("\ufeff").strip() if k else k): v for k, v in raw_row.items()}

        code = (row.get("代码") or "").strip().lstrip("'").strip('"').strip()
        name = (row.get("名称") or "").strip().strip('"').strip()
        industry = (row.get("所属行业") or "").strip().strip('"').strip()

        if not code or industry in MISSING_INDUSTRY_PLACEHOLDERS:
            skipped += 1
            continue

        grouped.setdefault(industry, []).append({"stock_code": code, "stock_name": name})

    logger.info(
        "CSV解析完成：共 %d 行，识别出 %d 个行业，跳过 %d 行（代码或所属行业为空）",
        total,
        len(grouped),
        skipped,
    )
    return grouped
