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

    return {
        "trade_date": str(trade_date),
        "time_points": [timezone.localtime(point).strftime("%H:%M") for point in time_axis],
        "series": selected_inflows + selected_outflows,
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
