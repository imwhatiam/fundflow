"""将开盘啦 RealRankingInfo 的数组记录转换为应用内板块行字典。

开盘啦返回的 list 每行是一个定长数组。已实测 19 列，下标语义如下（与
crawler_batch.py 的列名一致）：

    0  父代码       1  父板块       2  强度         3  涨幅         4  涨速
    5  成交额       6  主力净额     7  主力买       8  主力卖       9  量比
    10 流通市值     11 未用         12 300万大单净额 13 总市值      14 机构增仓
    15 2026平均PE   16 2027平均PE   17 强度(重复)   18 涨幅(重复)

其中 [17]、[18] 是 [2]、[3] 的冗余重复值，直接丢弃。开盘啦不提供板块指数、
主力净占比及超大/大/中/小单拆分，这些字段不在本映射中，避免伪造。
"""

SECTOR_CODE_INDEX = 0
SECTOR_NAME_INDEX = 1
CHANGE_PCT_INDEX = 3
TURNOVER_AMOUNT_INDEX = 5
MAIN_NET_INFLOW_INDEX = 6
MAIN_BUY_INDEX = 7
MAIN_SELL_INDEX = 8
VOLUME_RATIO_INDEX = 9
FLOAT_MARKET_CAP_INDEX = 10
LARGE_ORDER_NET_INFLOW_INDEX = 12
TOTAL_MARKET_CAP_INDEX = 13

MIN_ROW_LENGTH = TOTAL_MARKET_CAP_INDEX + 1


def optional_number(value):
    """将上游空值标记统一转换为 None，其余数值保留给 Django DecimalField。"""
    if value in (None, "-", "", "--", "null", "NULL"):
        return None
    return value


def parse_sector_row(item):
    """清洗一条开盘啦板块记录；没有代码或主力净流入时返回 None。"""
    if not isinstance(item, (list, tuple)) or len(item) < MIN_ROW_LENGTH:
        return None

    sector_code = str(item[SECTOR_CODE_INDEX]).strip() if item[SECTOR_CODE_INDEX] is not None else ""
    main_net_inflow = optional_number(item[MAIN_NET_INFLOW_INDEX])
    if not sector_code or main_net_inflow is None:
        return None

    return {
        "sector_code": sector_code,
        "sector_name": str(item[SECTOR_NAME_INDEX] or "").strip(),
        "change_pct": optional_number(item[CHANGE_PCT_INDEX]),
        "main_net_inflow": main_net_inflow,
        "main_buy": optional_number(item[MAIN_BUY_INDEX]),
        "main_sell": optional_number(item[MAIN_SELL_INDEX]),
        "large_order_net_inflow": optional_number(item[LARGE_ORDER_NET_INFLOW_INDEX]),
        "volume_ratio": optional_number(item[VOLUME_RATIO_INDEX]),
        "turnover_amount": optional_number(item[TURNOVER_AMOUNT_INDEX]),
        "float_market_cap": optional_number(item[FLOAT_MARKET_CAP_INDEX]),
        "total_market_cap": optional_number(item[TOTAL_MARKET_CAP_INDEX]),
    }
