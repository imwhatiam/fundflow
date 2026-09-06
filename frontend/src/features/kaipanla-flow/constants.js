/** 前端一次向服务端请求的每个方向最大候选数。 */
export const KPL_REQUEST_INFLOW_TOP = 25;
export const KPL_REQUEST_OUTFLOW_TOP = 25;

/** 新交易日首次加载时，默认在图表中展示的每个方向板块数。 */
export const KPL_DEFAULT_INFLOW_TOP = 5;
export const KPL_DEFAULT_OUTFLOW_TOP = 5;

/**
 * 生成 A 股交易时段内固定间隔（默认 5 分钟）的完整时间刻度。
 * 午间休市从 11:30 直接跳到 13:00，不产生 11:35–12:55 的刻度。
 * @param {number} [intervalMinutes=5] 刻度间隔分钟数
 * @returns {string[]} 形如 "09:30" 的刻度标签数组
 */
export function buildKaipanlaTimePoints(intervalMinutes = 5) {
  const sessions = [
    ["09:30", "11:30"],
    ["13:00", "15:00"],
  ];
  const points = [];
  for (const [start, end] of sessions) {
    let cursor = toMinutes(start);
    const endMinutes = toMinutes(end);
    while (cursor <= endMinutes) {
      points.push(toHHMM(cursor));
      cursor += intervalMinutes;
    }
  }
  return points;
}

/** 开盘啦分时折线图使用的 5 分钟交易刻度（上午 25 点 + 下午 25 点 = 50 个点）。 */
export const KPL_TRADING_TIME_POINTS = buildKaipanlaTimePoints(5);

/** 横轴标签显示间隔：每 3 个 5 分钟刻度（即 15 分钟）显示一个标签。 */
export const KPL_AXIS_LABEL_INTERVAL = 3;

function toMinutes(hhmm) {
  const [hour, minute] = hhmm.split(":").map(Number);
  return hour * 60 + minute;
}

function toHHMM(totalMinutes) {
  const hour = Math.floor(totalMinutes / 60);
  const minute = totalMinutes % 60;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}
