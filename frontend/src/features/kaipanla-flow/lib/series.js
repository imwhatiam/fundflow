/**
 * 将 API 返回的板块曲线按当前资金方向排序。
 * 正数是净流入，负数是净流出；零值不属于任何排行榜。
 */
export function splitKaipanlaSeriesByDirection(series) {
  const inflows = series
    .filter((item) => item.latest_net_inflow > 0)
    .sort((left, right) => right.latest_net_inflow - left.latest_net_inflow);
  const outflows = series
    .filter((item) => item.latest_net_inflow < 0)
    .sort((left, right) => left.latest_net_inflow - right.latest_net_inflow);

  return { inflows, outflows };
}

/** 返回一个新交易日图表默认应选中的板块代码集合。 */
export function getKaipanlaDefaultSelectedCodes(series, inflowTop, outflowTop) {
  const { inflows, outflows } = splitKaipanlaSeriesByDirection(series);
  const inflowCodes = inflows.slice(0, inflowTop).map((item) => item.code);
  const outflowCodes = outflows.slice(0, outflowTop).map((item) => item.code);
  return new Set([...inflowCodes, ...outflowCodes]);
}

/** 仅保留用户勾选、需要传给图表展示的曲线。 */
export function getKaipanlaSelectedSeries(series, selectedCodes) {
  return series.filter((item) => selectedCodes.has(item.code));
}
