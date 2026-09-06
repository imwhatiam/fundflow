"""将开盘啦板块数据库行转换为分时 API payload 的纯数据逻辑。"""

from collections import defaultdict

from django.utils import timezone


def empty_kaipanla_intraday_payload(trade_date):
    """返回没有可展示快照时的稳定 API 结构。"""
    return {
        "trade_date": str(trade_date),
        "time_points": [],
        "series": [],
    }


def build_values_by_sector(snapshot_rows):
    """按板块代码和快照时间组织净流入值。"""
    values_by_sector = defaultdict(dict)
    names_by_sector = {}

    for row in snapshot_rows:
        sector_code = row["sector_code"]
        names_by_sector[sector_code] = row["sector_name"]
        values_by_sector[sector_code][row["snapshot_time"]] = float(row["main_net_inflow"])

    return values_by_sector, names_by_sector


def codes_at_time(values_by_sector, snapshot_time):
    """找出指定刻度实际出现的板块代码。"""
    return {
        sector_code
        for sector_code, values_by_time in values_by_sector.items()
        if snapshot_time in values_by_time
    }


def resolve_source_time(time_axis, values_by_sector):
    """选择最近一个可用的快照刻度作为当前榜单来源。

    开盘啦单接口返回全量板块，不存在东财流入/流出两份榜单，因此只要当前刻度
    有数据即可作为候选来源；否则严格回退到立即前一个有数据的刻度。
    """
    for index in range(len(time_axis) - 1, -1, -1):
        snapshot_time = time_axis[index]
        codes = codes_at_time(values_by_sector, snapshot_time)
        if codes:
            return snapshot_time, codes

    return None, set()


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
    inflow_top,
    outflow_top,
    additional_codes=(),
):
    """构造完整的开盘啦板块分时响应，不读取数据库也不访问缓存。"""
    if not time_axis:
        return empty_kaipanla_intraday_payload(trade_date)

    values_by_sector, names_by_sector = build_values_by_sector(snapshot_rows)
    if not values_by_sector:
        return empty_kaipanla_intraday_payload(trade_date)

    source_time, source_codes = resolve_source_time(time_axis, values_by_sector)

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
    }


def build_kaipanla_intraday_close_payload(payload, selected_codes):
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
    }


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


def build_kaipanla_intraday_history_payload(*, end_date, items, period_rankings):
    """构造固定交易日窗口的 15:00 数据和累计排行。"""
    return {
        "end_date": str(end_date),
        "items": items,
        "period_rankings": period_rankings,
    }
