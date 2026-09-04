/** 返回最近一个有可展示曲线的交易日数据。 */
export function getLatestPopulatedDay(items) {
  return items.find((item) => item.series?.length > 0) || null;
}

/** 将日期和固定收盘刻度格式化为紧凑坐标轴标签。 */
export function formatHistoryAxisTime(value) {
  const [date = "", time = "15:00"] = String(value).split(" ");
  return `${date.slice(5)}\n${time}`;
}

/**
 * 将逐日 API 载荷拼成跨交易日的收盘曲线。
 * 每个交易日只读取该日最后一个分时值，并固定标记为 15:00。
 */
export function buildHistorySeries(items, selectedSeries) {
  const days = [...items].reverse();
  const timePoints = days.map((day) => `${day.trade_date} 15:00`);
  const seriesByCode = new Map(
    selectedSeries.map((item) => [item.code, {
      code: item.code,
      name: item.name,
      latest_net_inflow: item.latest_net_inflow,
      data: [],
    }]),
  );

  const previousValues = new Map();
  days.forEach((day) => {
    const dailySeriesByCode = new Map(
      (day.series || []).map((item) => [item.code, item]),
    );

    seriesByCode.forEach((historySeries, code) => {
      const dailySeries = dailySeriesByCode.get(code);
      const latestValue = dailySeries?.data?.[dailySeries.data.length - 1];
      if (Number.isFinite(latestValue)) {
        previousValues.set(code, latestValue);
      }
      historySeries.data.push(previousValues.get(code) ?? null);
    });
  });

  return { timePoints, series: [...seriesByCode.values()] };
}

/** 将窗口累计排行转换为排行榜和图表共用的系列。 */
export function buildPeriodRankingSeries(periodRankings) {
  const toSeries = (items) => items.map((item) => ({
    ...item,
    latest_net_inflow: Number(item.net_inflow_total) || 0,
  }));
  const inflows = toSeries(periodRankings?.inflows || []);
  const outflows = toSeries(periodRankings?.outflows || []);

  return { inflows, outflows, series: [...inflows, ...outflows] };
}

