import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";

// 红=净流入(仿A股"红涨"惯例)，绿=净流出。按幅度分深浅，最强的两个正/负值加粗，
// 呼应截图里"芯片/通信"字体明显更大更粗、中间几条细灰线的视觉层级。
const RED_SHADES = ["#c1352b", "#d97a6f", "#eec2ba"];
const GREEN_SHADES = ["#1f6f52", "#5f9c85", "#bcdccf"];
// 使用离散交易刻度而非连续时间轴，避免午间休市显示 11:45 至 12:45。
// 同时保留全天坐标范围，便于盘中和收盘后查看时保持一致。
const TRADING_TIME_POINTS = [
  "09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30",
  "13:00", "13:15", "13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00",
];

function alignSeriesData(timePoints, values) {
  const valueByTime = new Map(
    timePoints.map((time, index) => [time, values[index]]),
  );
  return TRADING_TIME_POINTS.map((time) => {
    const value = valueByTime.get(time);
    return Number.isFinite(value) ? value : null;
  });
}

function buildSeriesStyle(series) {
  const positives = series
    .filter((s) => s.latest_net_inflow >= 0)
    .sort((a, b) => b.latest_net_inflow - a.latest_net_inflow);
  const negatives = series
    .filter((s) => s.latest_net_inflow < 0)
    .sort((a, b) => a.latest_net_inflow - b.latest_net_inflow);

  const style = {};
  positives.forEach((s, i) => {
    style[s.code] = { color: RED_SHADES[Math.min(i, RED_SHADES.length - 1)], bold: i < 2 };
  });
  negatives.forEach((s, i) => {
    style[s.code] = { color: GREEN_SHADES[Math.min(i, GREEN_SHADES.length - 1)], bold: i < 2 };
  });
  return style;
}

function formatYi(value) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}亿`;
}

/**
 * 行业板块分时累计净流入多曲线图。
 * data: { time_points: string[], series: [{code, name, latest_net_inflow, data:number[]}] }
 */
export default function SectorFlowChart({ data }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);

  const styleMap = useMemo(() => buildSeriesStyle(data.series), [data.series]);

  useEffect(() => {
    if (!containerRef.current) return;
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current);
    }
    const chart = chartRef.current;

    const option = {
      grid: { left: 56, right: 104, top: 24, bottom: 52 },
      xAxis: {
        type: "category",
        data: TRADING_TIME_POINTS,
        boundaryGap: false,
        axisLine: { lineStyle: { color: "#e0e0e0" } },
        axisLabel: {
          color: "#b0b0b0",
          fontSize: 10,
          interval: 0,
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
        axisLabel: { color: "#b0b0b0", fontSize: 11, formatter: (v) => `${v}亿` },
      },
      tooltip: {
        trigger: "axis",
        formatter: (params) => {
          const time = params[0]?.axisValue ?? TRADING_TIME_POINTS[0];
          const rows = params
            .filter((p) => Number.isFinite(p.value))
            .sort((a, b) => b.value - a.value)
            .map(
              (p) =>
                `<div style="display:flex;justify-content:space-between;gap:16px;">
                   <span>${p.marker}${p.seriesName}</span>
                   <span>${formatYi(p.value)}</span>
                 </div>`
            )
            .join("");
          return `<div style="font-size:12px;margin-bottom:4px;color:#888">${time}</div>${rows}`;
        },
      },
      series: data.series.map((s) => {
        const st = styleMap[s.code] || { color: "#999", bold: false };
        return {
          name: s.name,
          type: "line",
          data: alignSeriesData(data.time_points, s.data),
          showSymbol: false,
          lineStyle: { width: st.bold ? 2 : 1.25, color: st.color },
          itemStyle: { color: st.color },
          emphasis: { focus: "series" },
          endLabel: {
            show: true,
            formatter: () => `${s.name} ${formatYi(s.latest_net_inflow)}`,
            color: st.color,
            fontWeight: st.bold ? 600 : 400,
            fontSize: st.bold ? 12 : 11,
          },
          labelLayout: { moveOverlap: "shiftY" },
          z: st.bold ? 3 : 2,
        };
      }),
    };

    chart.setOption(option, true);

    const handleResize = () => chart.resize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [data, styleMap]);

  // 组件彻底卸载时才销毁实例
  useEffect(() => {
    return () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  return <div ref={containerRef} style={{ width: "100%", height: 440 }} />;
}
