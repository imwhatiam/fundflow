import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";

import {
  buildHistorySeries,
  formatHistoryAxisTime,
  formatHistoryEndLabel,
} from "../lib/historySeries";

const RED_SHADES = ["#c1352b", "#d97a6f", "#eec2ba"];
const GREEN_SHADES = ["#1f6f52", "#5f9c85", "#bcdccf"];

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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** 跨多个交易日展示板块每日 15:00 的累计资金流。 */
export default function SectorFlowHistoryChart({ items, series }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const history = useMemo(
    () => buildHistorySeries(items, series),
    [items, series],
  );
  const styleByCode = useMemo(() => buildSeriesStyle(series), [series]);

  useEffect(() => {
    if (!containerRef.current) {
      return undefined;
    }
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current);
    }

    const chart = chartRef.current;
    const option = {
      grid: { left: 56, right: 180, top: 24, bottom: 90 },
      dataZoom: [{ type: "inside" }, { bottom: 24, height: 18, type: "slider" }],
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: history.timePoints,
        axisLine: { lineStyle: { color: "#e0e0e0" } },
        axisLabel: {
          color: "#b0b0b0",
          fontSize: 10,
          formatter: formatHistoryAxisTime,
          hideOverlap: false,
          interval: 0,
        },
        axisTick: { alignWithLabel: true, show: true, lineStyle: { color: "#e0e0e0" } },
      },
      yAxis: {
        type: "value",
        name: "主力净流入 · 亿元",
        nameTextStyle: { color: "#b0b0b0", fontSize: 11 },
        splitLine: { lineStyle: { color: "#f0f0f0" } },
        axisLabel: { color: "#b0b0b0", fontSize: 11, formatter: (value) => `${value}亿` },
      },
      tooltip: {
        trigger: "axis",
        formatter: (params) => {
          const time = params[0]?.axisValue ?? "";
          const rows = params
            .filter((item) => Number.isFinite(item.value))
            .sort((left, right) => right.value - left.value)
            .map(
              (item) =>
                `<div style="display:flex;justify-content:space-between;gap:16px;">\n                   <span>${item.marker}${escapeHtml(item.seriesName)}</span>\n                   <span>${formatYi(item.value)}</span>\n                 </div>`,
            )
            .join("");
          return `<div style="font-size:12px;margin-bottom:4px;color:#888">${escapeHtml(formatHistoryAxisTime(time).replace("\n", " "))}</div>${rows}`;
        },
      },
      series: history.series.map((item) => {
        const style = styleByCode[item.code] || { color: "#999", bold: false };
        return {
          name: item.name,
          type: "line",
          data: item.data,
          showSymbol: true,
          connectNulls: false,
          lineStyle: { width: style.bold ? 2 : 1.25, color: style.color },
          itemStyle: { color: style.color },
          emphasis: { focus: "series" },
          endLabel: {
            show: true,
            formatter: () => formatHistoryEndLabel(item.name, item.latest_net_inflow),
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
  }, [history, styleByCode]);

  useEffect(() => () => {
    chartRef.current?.dispose();
    chartRef.current = null;
  }, []);

  return (
    <div
      aria-label="历史走势图：每个交易日仅显示 15:00 数据"
      data-trade-day-count={history.timePoints.length}
      ref={containerRef}
      role="img"
      style={{ width: "100%", height: 500 }}
    />
  );
}
