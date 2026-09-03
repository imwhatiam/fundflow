"""将开盘啦板块数据库行转换为分时 API payload 的纯数据逻辑。"""

from collections import defaultdict

from django.utils import timezone


def empty_kaipanla_intraday_payload(trade_date):
    """返回没有可展示快照时的稳定 API 结构。"""
    return {
        "trade_date": str(trade_date),
        "time_points": [],
        "series": [],
        "stale": True,
    }


def build_values_by_sector(snapshot_rows):
    """按板块代码和快照时间组织净流入值。"""
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


def codes_at_time(values_by_sector, snapshot_time):
    """找出指定刻度实际出现的板块代码。"""
    return {
        sector_code
        for sector_code, values_by_time in values_by_sector.items()
        if snapshot_time in values_by_time
    }


def resolve_source_time(time_axis, values_by_sector, status_by_time):
    """选择最近一个可用的快照刻度作为当前榜单来源。

    开盘啦单接口返回全量板块，不存在东财流入/流出两份榜单，因此只要当前刻度
    有数据且抓取成功即可作为候选来源；否则严格回退到立即前一个有数据的刻度。
    """
    for index in range(len(time_axis) - 1, -1, -1):
        snapshot_time = time_axis[index]
        status = status_by_time.get(snapshot_time)
        if status is not None and not status["fetch_succeeded"]:
            continue
        codes = codes_at_time(values_by_sector, snapshot_time)
        if codes:
            return snapshot_time, codes, index != len(time_axis) - 1

    return None, set(), True


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


def select_sector_series(series, inflow_top, outflow_top):
    """分别选取净流入最高和净流出最多的板块，零值不归入任一侧。"""
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


def build_kaipanla_intraday_payload(
    *,
    trade_date,
    time_axis,
    snapshot_rows,
    status_rows,
    inflow_top,
    outflow_top,
):
    """构造完整的开盘啦板块分时响应，不读取数据库也不访问缓存。"""
    if not time_axis:
        return empty_kaipanla_intraday_payload(trade_date)

    values_by_sector, names_by_sector, available_times = build_values_by_sector(snapshot_rows)
    if not values_by_sector:
        return empty_kaipanla_intraday_payload(trade_date)

    status_by_time = build_status_by_time(status_rows)
    source_time, source_codes, source_stale = resolve_source_time(
        time_axis, values_by_sector, status_by_time
    )

    if source_time is None:
        return empty_kaipanla_intraday_payload(trade_date)

    series = [
        build_series_item(
            code=code,
            values_by_time=values_by_sector[code],
            name=names_by_sector[code],
            time_axis=time_axis,
            source_time=source_time,
        )
        for code in source_codes
    ]
    selected_series = select_sector_series(series, inflow_top, outflow_top)

    return {
        "trade_date": str(trade_date),
        "time_points": [timezone.localtime(point).strftime("%H:%M") for point in time_axis],
        "series": selected_series,
        "stale": is_stale(
            time_axis,
            available_times,
            status_by_time,
            source_stale,
        ),
    }


def is_stale(time_axis, available_times, status_by_time, source_stale):
    """根据缺失刻度与当前抓取状态计算 stale 标识。"""
    current_status = status_by_time.get(time_axis[-1])
    current_status_incomplete = current_status is not None and not current_status["fetch_succeeded"]
    return (
        not set(time_axis).issubset(available_times)
        or current_status_incomplete
        or source_stale
    )
