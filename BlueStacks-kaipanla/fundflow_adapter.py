#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将开盘啦个股列表转换为 fundflow 可消费的资金流快照 JSONL。

该脚本复用 crawler_batch.py 已验证的认证、请求和响应解码逻辑。输出每行一个
JSON 对象，字段名与 backend/fundflow/services/eastmoney_client.py 的
fetch_all_stock_fund_flow() 返回值保持一致，因此后续可由 fundflow 导入而不需要
重新解释开盘啦的数组字段。

开盘啦 ZhiShuStockList_W8 已确认提供：最新价、涨跌幅、成交额、主力买/卖/净额及
净流占比；它未提供成交量和超大/大/中/小单净流入，因此这些字段输出为 null。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import crawler_batch as crawler

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

# 开盘啦 ZhiShuStockList_W8 已验证的数组下标（不包含脚本加入的父/子板块字段）。
STOCK_CODE_INDEX = 0
STOCK_NAME_INDEX = 1
LATEST_PRICE_INDEX = 5
CHANGE_PCT_INDEX = 6
TURNOVER_AMOUNT_INDEX = 7
MAIN_BUY_INDEX = 11
MAIN_SELL_INDEX = 12
MAIN_NET_INFLOW_INDEX = 13
MAIN_NET_INFLOW_RATIO_INDEX = 19
MIN_STOCK_ROW_LENGTH = MAIN_NET_INFLOW_RATIO_INDEX + 1

FUND_FLOW_FIELDS = (
    "stock_code",
    "stock_name",
    "market",
    "latest_price",
    "change_pct",
    "volume",
    "turnover_amount",
    "main_net_inflow",
    "main_net_inflow_ratio",
    "super_large_net_inflow",
    "large_net_inflow",
    "medium_net_inflow",
    "small_net_inflow",
)


def _decimal_or_none(value: Any) -> Decimal | None:
    """将开盘啦的数值安全转换为 Decimal，保留缺失值。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "-", "None", "null", "NULL"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def market_for_code(stock_code: str) -> str | None:
    """将 A 股代码映射为 fundflow 的 SH/SZ/BJ 枚举；非 A 股返回 None。"""
    if stock_code.startswith(("60", "68")):
        return "SH"
    if stock_code.startswith(("00", "30")):
        return "SZ"
    if stock_code.startswith(("4", "8")):
        return "BJ"
    return None


def normalize_stock_row(item: list[Any] | tuple[Any, ...]) -> dict[str, Any] | None:
    """把一条 ZhiShuStockList_W8 数组记录映射为 fundflow 行。"""
    if len(item) < MIN_STOCK_ROW_LENGTH:
        return None

    raw_code = str(item[STOCK_CODE_INDEX]).strip()
    if not raw_code.isdigit() or len(raw_code) > 6:
        return None
    stock_code = raw_code.zfill(6)
    market = market_for_code(stock_code)
    stock_name = str(item[STOCK_NAME_INDEX] or "").strip()
    main_net_inflow = _decimal_or_none(item[MAIN_NET_INFLOW_INDEX])

    # fundflow 的板块曲线以主力净流入汇总，缺少该值的行不能形成有效快照。
    if not market or not stock_name or main_net_inflow is None:
        return None

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "market": market,
        "latest_price": _decimal_or_none(item[LATEST_PRICE_INDEX]),
        "change_pct": _decimal_or_none(item[CHANGE_PCT_INDEX]),
        # ZhiShuStockList_W8 没有成交量字段。
        "volume": None,
        "turnover_amount": _decimal_or_none(item[TURNOVER_AMOUNT_INDEX]),
        "main_net_inflow": main_net_inflow,
        "main_net_inflow_ratio": _decimal_or_none(item[MAIN_NET_INFLOW_RATIO_INDEX]),
        # 开盘啦该接口未按东财口径拆分四类订单，必须显式保留为空。
        "super_large_net_inflow": None,
        "large_net_inflow": None,
        "medium_net_inflow": None,
        "small_net_inflow": None,
    }


def _coerce_csv_row(row: dict[str, str]) -> list[str]:
    """将 crawler_batch.py 输出的 stock_info CSV 行还原为原始数组顺序。"""
    return [
        row.get("代码", ""),
        row.get("名称", ""),
        "",  # 原始数组 [2]
        "",  # 原始数组 [3]
        row.get("所属板块标签", ""),
        row.get("价格", ""),
        row.get("涨幅", ""),
        row.get("成交额", ""),
        row.get("实际换手率", ""),
        row.get("涨速", ""),
        row.get("实际流通", ""),
        row.get("主力买", ""),
        row.get("主力卖", ""),
        row.get("主力净额", ""),
        "", "", "", "",  # 原始数组 [14:18]
        row.get("卖流占比", ""),
        row.get("净流占比", ""),
    ]


def normalize_rows(items: Iterable[list[Any] | tuple[Any, ...]]) -> list[dict[str, Any]]:
    """标准化并按股票代码去重，保留第一条有效的最新记录。"""
    rows_by_code: dict[str, dict[str, Any]] = {}
    for item in items:
        row = normalize_stock_row(item)
        if row is not None:
            rows_by_code.setdefault(row["stock_code"], row)
    return [rows_by_code[code] for code in sorted(rows_by_code)]


def parse_types(value: str) -> list[int]:
    """解析 `6`、`0,6,19` 或 `all` 为开盘啦 Type 列表。"""
    if value.strip().lower() == "all":
        return list(range(20))
    try:
        types = sorted({int(part.strip()) for part in value.split(",")})
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--types 必须是 0-19 的逗号分隔列表或 all") from exc
    if not types or any(item < 0 or item > 19 for item in types):
        raise argparse.ArgumentTypeError("--types 的取值范围为 0-19")
    return types


class KplApiError(RuntimeError):
    """开盘啦接口返回业务错误，不能将结果当作正常空列表。"""


def _response_list(response: dict[str, Any] | None, key: str, label: str) -> list[Any]:
    if response is None:
        raise KplApiError(f"{label} 请求或响应解码失败")
    if str(response.get("errcode", "0")) != "0":
        raise KplApiError(f"{label} 返回 errcode={response.get('errcode')}: {response.get('errmsg', '未知错误')}")
    value = response.get(key, [])
    if not isinstance(value, list):
        raise KplApiError(f"{label} 响应中的 {key} 不是列表")
    return value


def discover_sub_plate_ids(
    trade_date: str, max_plates: int | None = None, max_pages: int = 100
) -> list[str]:
    """复用批量爬虫的板块发现流程，获取成分股接口所需的子板块代码。"""
    parent_ids: list[str] = []
    seen_first_ids: set[str] = set()
    for page in range(max_pages):
        response = crawler.do_request(
            {
                "Order": "1",
                "a": "RealRankingInfo",
                "st": "30",
                "c": "ZhiShuRanking",
                "PhoneOSNew": crawler.PHONE_OS_NEW,
                "DeviceID": crawler.DEVICE_ID,
                "VerSion": crawler.VERSION,
                "Index": str(page * 30),
                "Date": trade_date,
                "apiv": crawler.API_VERSION,
                "Type": "1",
                "ZSType": "7",
            },
            f"RealRankingInfo[{trade_date}@{page}]",
        )
        items = _response_list(response, "list", f"RealRankingInfo[{trade_date}@{page}]")
        if not items:
            break
        first_id = str(items[0][0]) if items and items[0] else ""
        if not first_id or first_id in seen_first_ids:
            break
        seen_first_ids.add(first_id)
        for item in items:
            if item and item[0] is not None:
                parent_id = str(item[0])
                if parent_id not in parent_ids:
                    parent_ids.append(parent_id)
        # 验证模式只需要一个可用子板块；不再继续翻页，避免“--max-plates 1”
        # 仍触发全量父板块分页请求。
        if max_plates is not None and parent_ids:
            break

    sub_plate_ids: list[str] = []
    for parent_id in parent_ids:
        response = crawler.do_request(
            {
                "a": "SonPlate_Info",
                "c": "ZhiShuRanking",
                "PhoneOSNew": crawler.PHONE_OS_NEW,
                "DeviceID": crawler.DEVICE_ID,
                "VerSion": crawler.VERSION,
                "IsShow": "1",
                "Date": trade_date,
                "apiv": crawler.API_VERSION,
                "PlateID": parent_id,
            },
            f"SonPlate[{parent_id}]",
        )
        children = _response_list(response, "List", f"SonPlate[{parent_id}]")
        if not children:
            # 没有子板块时，该父板块本身可以作为成分股列表的 PlateID。
            children = [[parent_id]]
        for child in children:
            if child and child[0] is not None:
                sub_plate_id = str(child[0])
                if sub_plate_id not in sub_plate_ids:
                    sub_plate_ids.append(sub_plate_id)
                    if max_plates is not None and len(sub_plate_ids) >= max_plates:
                        return sub_plate_ids
    return sub_plate_ids


def fetch_live_items(trade_date: str, types: list[int], max_plates: int | None) -> list[list[Any]]:
    """发现板块后抓取原始个股列表；串行且使用 crawler_batch 的随机延时/重试。"""
    sub_plate_ids = discover_sub_plate_ids(trade_date, max_plates=max_plates)
    print(f"发现 {len(sub_plate_ids)} 个子板块，将请求 {len(sub_plate_ids) * len(types)} 个个股列表。")

    items: list[list[Any]] = []
    for index, plate_id in enumerate(sub_plate_ids, start=1):
        for type_value in types:
            response = crawler.fetch_stock_list(plate_id, trade_date, type_value)
            items.extend(_response_list(response, "list", f"StockList[{plate_id}@type={type_value}]"))
        if index % 25 == 0 or index == len(sub_plate_ids):
            print(f"已完成 {index}/{len(sub_plate_ids)} 个子板块，累计原始记录 {len(items)} 条。")
    return items


def write_jsonl(rows: Iterable[dict[str, Any]], output_path: Path) -> int:
    """写入 fundflow 标准 JSONL；Decimal 作为字符串避免精度丢失。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":")))
            output.write("\n")
            count += 1
    return count


def read_stock_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return [_coerce_csv_row(row) for row in csv.DictReader(source)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导出与 fundflow 兼容的开盘啦个股资金流 JSONL")
    parser.add_argument(
        "--date",
        help="历史交易日期，格式 YYYY-MM-DD（apphis 历史接口当前不接受当天日期）",
    )
    parser.add_argument(
        "--types",
        default="6",
        help="开盘啦排序 Type：如 6、0,6,19 或 all（all 需要显式确认高请求量）",
    )
    parser.add_argument("--allow-high-request-volume", action="store_true", help="确认执行 --types all 的高请求量抓取")
    parser.add_argument("--max-plates", type=int, help="仅抓前 N 个子板块，用于验证")
    parser.add_argument("--input-csv", type=Path, help="转换已有 stock_info CSV，不发网络请求")
    parser.add_argument("--delay", type=float, default=0.25, help="每个请求前的最小随机延迟（秒），默认 0.25")
    parser.add_argument("--output", type=Path, help="输出 JSONL 路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    types = parse_types(args.types)
    if types == list(range(20)) and not args.allow_high_request_volume:
        print("拒绝执行：--types all 可能产生上万请求；如确认需要，请添加 --allow-high-request-volume。", file=sys.stderr)
        return 2
    if args.max_plates is not None and args.max_plates <= 0:
        print("--max-plates 必须大于 0。", file=sys.stderr)
        return 2
    if args.delay < 0:
        print("--delay 不能小于 0。", file=sys.stderr)
        return 2

    if not args.date:
        print("必须显式指定 --date，例如 --date 2026-08-25。", file=sys.stderr)
        return 2

    output_path = args.output or DATA_DIR / f"fundflow_stock_fund_flow_{args.date}.jsonl"
    if args.input_csv:
        raw_items = read_stock_csv(args.input_csv)
        source_label = f"CSV {args.input_csv}"
    else:
        crawler.load_env()
        if not crawler.USER_ID or not crawler.TOKEN:
            print("未在 .env 中读取到 KPL_USER_ID / KPL_TOKEN。", file=sys.stderr)
            return 1
        if not crawler.validate_token():
            print("开盘啦 Token 无效或已过期；请先通过 BlueStacks Air 重新抓包更新 .env。", file=sys.stderr)
            return 1
        crawler._DELAY_MIN = args.delay
        crawler._DELAY_MAX = max(args.delay * 2, args.delay)
        try:
            raw_items = fetch_live_items(args.date, types, args.max_plates)
        except KplApiError as exc:
            print(f"开盘啦接口未返回可用数据：{exc}", file=sys.stderr)
            if args.date == date.today().isoformat():
                print(
                    "提示：当前已验证的 apphis 历史接口不接受当天日期；"
                    "若需要 15 分钟实时快照，请先在 App 的个股页面抓取对应的实时请求。",
                    file=sys.stderr,
                )
            return 1
        source_label = "开盘啦历史接口"

    rows = normalize_rows(raw_items)
    if not rows:
        print("上游请求成功但未解析出有效 A 股资金流，未写入空快照。", file=sys.stderr)
        return 1
    written = write_jsonl(rows, output_path)
    print(f"{source_label}：原始记录 {len(raw_items)} 条，去重后有效 A 股 {written} 只。")
    print(f"已输出 fundflow 兼容 JSONL：{output_path}")
    print("说明：volume 与超大/大/中/小单净流入为 null，因为 ZhiShuStockList_W8 不提供这些字段。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
