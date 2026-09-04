"""将三级行业数据库行转换为分时 API payload 的纯数据逻辑。"""

from collections import defaultdict

from django.utils import timezone


def empty_sector_intraday_payload(trade_date):
    """返回没有可展示快照时的稳定 API 结构。"""
    return {
        "trade_date": str(trade_date),
        "time_points": [],
        "series": [],
        "stale": True,
    }


def build_values_by_sector(snapshot_rows):
    """按行业代码和快照时间组织净流入值。"""
    values_by_sector = defaultdict(dict)
    names_by_sector = {}
    available_times = set()

    for row in snapshot_rows:
        sector_code = row["sector_code"]
        names_by_sector[sector_code] = row["sector_name"]
        values_by_sector[sector_code][row["snapshot_time"]] = float(row["main_net_inflow"])
        available_times.add(row["snapshot_time"])

    return values_by_sector, names_by_sector, available_times


def build_status_by_time(status_rows):
    """将状态行组织为以快照时间为键的字典。"""
    return {row["snapshot_time"]: row for row in status_rows}


def select_sector_series(series, inflow_top, outflow_top):
    """分别选取净流入最高和净流出最多的行业，零值不归入任一侧。"""
    inflows = sorted(
        (item for item in series if item["latest_net_inflow"] > 0),
        key=lambda item: item["latest_net_inflow"],
        reverse=True,
    )[:inflow_top]
    outflows = sorted(
        (item for item in series if item["latest_net_inflow"] < 0),
        key=lambda item: item["latest_net_inflow"],
    )[:outflow_top]
    return inflows + outflows


def direction_source_time(time_axis, values_by_sector, status_by_time, *, direction, predicate):
    """当前方向不可用时，严格选择立即前一个 15 分钟刻度。"""
    current_time = time_axis[-1]
    current_status = status_by_time.get(current_time)
    current_request_succeeded = (
        current_status is None or current_status[f"{direction}_succeeded"]
    )
    current_codes = set()
    if current_request_succeeded:
        current_codes = codes_for_direction(values_by_sector, current_time, predicate)

    if current_codes:
        return current_time, current_codes, False
    if len(time_axis) < 2:
        return None, set(), True

    previous_time = time_axis[-2]
    previous_codes = codes_for_direction(values_by_sector, previous_time, predicate)
    return previous_time, previous_codes, True


def codes_for_direction(values_by_sector, snapshot_time, predicate):
    """找出指定刻度实际出现并符合净流入方向的行业代码。"""
    return {
        sector_code
        for sector_code, values_by_time in values_by_sector.items()
        if snapshot_time in values_by_time and predicate(values_by_time[snapshot_time])
    }


def build_series_item(*, code, values_by_time, name, time_axis, source_time):
    """沿离散时间轴前向填充一条曲线，并在回退时固定当前点。"""
    current_time = time_axis[-1]
    values_in_yi = []
    last_value = 0.0

    for snapshot_time in time_axis:
        if snapshot_time in values_by_time:
            last_value = values_by_time[snapshot_time]
        values_in_yi.append(round(last_value / 1e8, 4))

    if source_time != current_time:
        values_in_yi[-1] = round(values_by_time[source_time] / 1e8, 4)

    return {
        "code": code,
        "name": name,
        "latest_net_inflow": values_in_yi[-1],
        "data": values_in_yi,
    }


def build_sector_intraday_payload(
    *,
    trade_date,
    time_axis,
    snapshot_rows,
    status_rows,
    inflow_top,
    outflow_top,
    additional_codes=(),
):
    """构造完整的三级行业分时响应，不读取数据库也不访问缓存。"""
    if not time_axis:
        return empty_sector_intraday_payload(trade_date)

    values_by_sector, names_by_sector, available_times = build_values_by_sector(snapshot_rows)
    if not values_by_sector:
        return empty_sector_intraday_payload(trade_date)

    status_by_time = build_status_by_time(status_rows)
    inflow_time, inflow_codes, inflow_missing = direction_source_time(
        time_axis,
        values_by_sector,
        status_by_time,
        direction="inflow",
        predicate=lambda value: value > 0,
    )
    outflow_time, outflow_codes, outflow_missing = direction_source_time(
        time_axis,
        values_by_sector,
        status_by_time,
        direction="outflow",
        predicate=lambda value: value < 0,
    )

    inflow_series = build_direction_series(
        inflow_codes, values_by_sector, names_by_sector, time_axis, inflow_time
    )
    outflow_series = build_direction_series(
        outflow_codes, values_by_sector, names_by_sector, time_axis, outflow_time
    )
    selected_inflows = sorted(
        inflow_series,
        key=lambda item: item["latest_net_inflow"],
        reverse=True,
    )[:inflow_top]
    selected_inflow_codes = {item["code"] for item in selected_inflows}
    selected_outflows = [
        item for item in sorted(outflow_series, key=lambda item: item["latest_net_inflow"])
        if item["code"] not in selected_inflow_codes
    ][:outflow_top]

    selected_series = selected_inflows + selected_outflows
    selected_codes = {item["code"] for item in selected_series}
    additional_series = [
        build_series_item(
            code=code,
            values_by_time=values_by_sector[code],
            name=names_by_sector[code],
            time_axis=time_axis,
            source_time=time_axis[-1],
        )
        for code in sorted(set(additional_codes) - selected_codes)
        if code in values_by_sector
    ]

    return {
        "trade_date": str(trade_date),
        "time_points": [timezone.localtime(point).strftime("%H:%M") for point in time_axis],
        "series": selected_series + additional_series,
        "stale": is_stale(
            time_axis,
            available_times,
            status_by_time,
            inflow_missing,
            outflow_missing,
        ),
    }


def build_direction_series(codes, values_by_sector, names_by_sector, time_axis, source_time):
    """仅为已选方向的当前候选行业构造曲线。"""
    if source_time is None:
        return []
    return [
        build_series_item(
            code=code,
            values_by_time=values_by_sector[code],
            name=names_by_sector[code],
            time_axis=time_axis,
            source_time=source_time,
        )
        for code in codes
    ]


def build_sector_intraday_close_payload(payload, selected_codes):
    """将单日分时 payload 收窄为累计排行板块在 15:00 的数据。"""
    try:
        close_index = payload["time_points"].index("15:00")
    except ValueError:
        close_index = None

    series_by_code = {item["code"]: item for item in payload["series"]}
    close_series = []
    if close_index is not None:
        for code in selected_codes:
            item = series_by_code.get(code)
            if item is None or close_index >= len(item["data"]):
                continue
            close_value = item["data"][close_index]
            close_series.append(
                {
                    "code": code,
                    "name": item["name"],
                    "latest_net_inflow": close_value,
                    "data": [close_value],
                }
            )

    return {
        "trade_date": payload["trade_date"],
        "time_points": ["15:00"],
        "series": close_series,
        "stale": payload["stale"] or close_index is None or not close_series,
    }


def is_stale(time_axis, available_times, status_by_time, inflow_missing, outflow_missing):
    """根据缺失刻度、当前抓取状态和方向回退计算 stale 标识。"""
    current_status = status_by_time.get(time_axis[-1])
    current_status_incomplete = current_status is not None and not (
        current_status["inflow_succeeded"] and current_status["outflow_succeeded"]
    )
    return (
        not set(time_axis).issubset(available_times)
        or current_status_incomplete
        or inflow_missing
        or outflow_missing
    )


def build_period_rankings(snapshot_rows, inflow_top, outflow_top):
    """按窗口净流入总额排序，返回最高与最低的 Top N。"""
    totals_by_sector = {}

    for row in snapshot_rows:
        code = row["sector_code"]
        totals = totals_by_sector.setdefault(
            code,
            {
                "code": code,
                "name": row["sector_name"],
                "net_inflow_total": 0.0,
            },
        )
        totals["net_inflow_total"] += float(row["main_net_inflow"])

    def ranking_item(totals):
        net_inflow_total = round(totals["net_inflow_total"] / 1e8, 4)
        return {
            "code": totals["code"],
            "name": totals["name"],
            "inflow_total": max(net_inflow_total, 0.0),
            "outflow_total": max(-net_inflow_total, 0.0),
            "net_inflow_total": net_inflow_total,
        }

    all_totals = tuple(totals_by_sector.values())
    inflows = sorted(
        all_totals,
        key=lambda totals: (-totals["net_inflow_total"], totals["code"]),
    )[:inflow_top]
    outflows = sorted(
        all_totals,
        key=lambda totals: (totals["net_inflow_total"], totals["code"]),
    )[:outflow_top]
    return {
        "inflows": [ranking_item(totals) for totals in inflows],
        "outflows": [ranking_item(totals) for totals in outflows],
    }


def build_sector_intraday_history_payload(*, end_date, items, period_rankings):
    """构造固定交易日窗口的 15:00 数据和累计排行。"""
    return {
        "end_date": str(end_date),
        "items": items,
        "period_rankings": period_rankings,
    }
