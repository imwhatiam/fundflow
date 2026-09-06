import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";

// 红=净流入（A 股“红涨”惯例），绿=净流出。资金量更大的两条曲线加粗。
const RED_SHADES = ["#c1352b", "#d97a6f", "#eec2ba"];
const GREEN_SHADES = ["#1f6f52", "#5f9c85", "#bcdccf"];

// 使用离散交易刻度而非连续时间轴，避免午间休市显示 11:45 至 12:45。
// 无论当前盘中已采集到多少数据，始终保留全天完整的坐标范围。
const TRADING_TIME_POINTS = [
  "09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30",
  "13:00", "13:15", "13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00",
];

/** 将服务端已返回的值放回完整固定时间刻度；缺少的时点保持为空。 */
function alignSeriesData(sourcePoints, values, targetPoints) {
  const valueByTime = new Map(
    sourcePoints.map((time, index) => [time, values[index]]),
  );

  return targetPoints.map((time) => {
    const value = valueByTime.get(time);
    return Number.isFinite(value) ? value : null;
  });
}

function buildSeriesStyle(series) {
  const positives = series
    .filter((item) => item.latest_net_inflow >= 0)
    .sort((left, right) => right.latest_net_inflow - left.latest_net_inflow);
  const negatives = series
    .filter((item) => item.latest_net_inflow < 0)
    .sort((left, right) => left.latest_net_inflow - right.latest_net_inflow);

  const styleByCode = {};
  positives.forEach((item, index) => {
    styleByCode[item.code] = {
      color: RED_SHADES[Math.min(index, RED_SHADES.length - 1)],
      bold: index < 2,
    };
  });
  negatives.forEach((item, index) => {
    styleByCode[item.code] = {
      color: GREEN_SHADES[Math.min(index, GREEN_SHADES.length - 1)],
      bold: index < 2,
    };
  });
  return styleByCode;
}

function formatYi(value) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}亿`;
}

/** ECharts 的 HTML tooltip 必须转义来自上游接口的行业名称。 */
function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/**
 * 构造横轴标签的显示间隔。
 * 传入 0 时全部显示；传入正整数时按该间隔稀疏显示，但强制显示最后一个刻度
 * （收盘 15:00 是最关键的时间点），并跳过倒数第二个以免两个标签挤在一起。
 */
function resolveAxisLabelInterval(interval, axisLength) {
  if (interval <= 0 || axisLength <= 2) {
    return interval;
  }
  return (index) =>
    index === axisLength - 1 ||
    (index % interval === 0 && index !== axisLength - 2);
}

/**
 * 行业板块分时累计净流入多曲线图。
 * 横轴显示完整固定交易刻度（默认 15 分钟 18 点）；可通过 timePoints 覆盖，
 * 供不同数据源使用不同刻度间隔。服务端未返回的未来时点保持为空。
 * axisLabelInterval 控制横轴标签的显示间隔（默认 0 = 每个刻度都显示），
 * 用于在更细的刻度下只稀疏显示部分标签。
 */
export default function SectorFlowChart({
  data,
  timePoints = TRADING_TIME_POINTS,
  axisLabelInterval = 0,
}) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const styleByCode = useMemo(() => buildSeriesStyle(data.series), [data.series]);
  const axis = timePoints.length > 0 ? timePoints : TRADING_TIME_POINTS;
  const labelInterval = useMemo(
    () => resolveAxisLabelInterval(axisLabelInterval, axis.length),
    [axisLabelInterval, axis.length],
  );

  useEffect(() => {
    if (!containerRef.current) {
      return undefined;
    }
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current);
    }

    const chart = chartRef.current;
    const option = {
      grid: { left: 56, right: 104, top: 24, bottom: 52 },
      xAxis: {
        type: "category",
        data: axis,
        boundaryGap: false,
        axisLine: { lineStyle: { color: "#e0e0e0" } },
        axisLabel: {
          color: "#b0b0b0",
          fontSize: 10,
          interval: labelInterval,
          hideOverlap: false,
          rotate: 45,
        },
        axisTick: { show: true, lineStyle: { color: "#e0e0e0" } },
      },
      yAxis: {
        type: "value",
        name: "累计净额 · 亿元",
        nameTextStyle: { color: "#b0b0b0", fontSize: 11 },
        splitLine: { lineStyle: { color: "#f0f0f0" } },
        axisLabel: { color: "#b0b0b0", fontSize: 11, formatter: (value) => `${value}亿` },
      },
      tooltip: {
        trigger: "axis",
        formatter: (params) => {
          const time = params[0]?.axisValue ?? axis[0];
          const rows = params
            .filter((item) => Number.isFinite(item.value))
            .sort((left, right) => right.value - left.value)
            .map(
              (item) =>
                `<div style="display:flex;justify-content:space-between;gap:16px;">
                   <span>${item.marker}${escapeHtml(item.seriesName)}</span>
                   <span>${formatYi(item.value)}</span>
                 </div>`,
            )
            .join("");
          return `<div style="font-size:12px;margin-bottom:4px;color:#888">${escapeHtml(time)}</div>${rows}`;
        },
      },
      series: data.series.map((item) => {
        const style = styleByCode[item.code] || { color: "#999", bold: false };
        return {
          name: item.name,
          type: "line",
          data: alignSeriesData(data.time_points, item.data, axis),
          showSymbol: false,
          lineStyle: { width: style.bold ? 2 : 1.25, color: style.color },
          itemStyle: { color: style.color },
          emphasis: { focus: "series" },
          endLabel: {
            show: true,
            formatter: () => `${item.name} ${formatYi(item.latest_net_inflow)}`,
            color: style.color,
            fontWeight: style.bold ? 600 : 400,
            fontSize: style.bold ? 12 : 11,
          },
          labelLayout: { moveOverlap: "shiftY" },
          z: style.bold ? 3 : 2,
        };
      }),
    };

    chart.setOption(option, true);
    const handleResize = () => chart.resize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [data, styleByCode, axis, labelInterval]);

  useEffect(() => {
    return () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  return <div ref={containerRef} style={{ width: "100%", height: 440 }} />;
}
