"""将东方财富响应转换为应用内使用的行业行字典。"""


def extract_ranking_rows(payload):
    """读取响应中的 diff 列表，并兼容上游偶尔返回的字典形式。"""
    data = payload.get("data") or {}
    rows = data.get("diff") or []
    if isinstance(rows, dict):
        return list(rows.values())
    return rows if isinstance(rows, list) else []


def parse_sector_row(row):
    """清洗一条三级行业记录；没有代码或主力净流入时返回 None。"""
    sector_code = row.get("f12")
    main_net_inflow = optional_number(row, "f62")
    if not sector_code or main_net_inflow is None:
        return None

    return {
        "sector_code": sector_code,
        "sector_name": row.get("f14") or "",
        "latest_index": optional_number(row, "f2"),
        "change_pct": optional_number(row, "f3"),
        "main_net_inflow": main_net_inflow,
        "main_net_inflow_ratio": optional_number(row, "f184"),
        "super_large_net_inflow": optional_number(row, "f66"),
        "large_net_inflow": optional_number(row, "f72"),
        "medium_net_inflow": optional_number(row, "f78"),
        "small_net_inflow": optional_number(row, "f84"),
        # 仅用于确定 --latest 的快照时刻，不写入模型。
        "source_timestamp": optional_number(row, "f124"),
    }


def optional_number(row, field_name):
    """将上游空值标记统一转换为 None，其余数值保留给 Django DecimalField。"""
    value = row.get(field_name)
    if value in (None, "-", ""):
        return None
    return value
