/**
 * 将 API 返回的行业曲线按当前资金方向排序。
 * 正数是净流入，负数是净流出；零值不属于任何排行榜。
 */
export function splitSeriesByDirection(series) {
  const inflows = series
    .filter((item) => item.latest_net_inflow > 0)
    .sort((left, right) => right.latest_net_inflow - left.latest_net_inflow);
  const outflows = series
    .filter((item) => item.latest_net_inflow < 0)
    .sort((left, right) => left.latest_net_inflow - right.latest_net_inflow);

  return { inflows, outflows };
}

/** 返回一个新交易日图表默认应选中的行业代码集合。 */
export function getDefaultSelectedCodes(series, inflowTop, outflowTop) {
  const { inflows, outflows } = splitSeriesByDirection(series);
  const inflowCodes = inflows.slice(0, inflowTop).map((item) => item.code);
  const outflowCodes = outflows.slice(0, outflowTop).map((item) => item.code);
  return new Set([...inflowCodes, ...outflowCodes]);
}

/** 仅保留用户勾选、需要传给图表展示的曲线。 */
export function getSelectedSeries(series, selectedCodes) {
  const uniqueCodes = new Set();
  return series.filter((item) => {
    if (!selectedCodes.has(item.code) || uniqueCodes.has(item.code)) {
      return false;
    }
    uniqueCodes.add(item.code);
    return true;
  });
}
