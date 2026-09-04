import assert from "node:assert/strict";
import test from "node:test";

import {
  buildHistorySeries,
  buildPeriodRankingSeries,
  formatHistoryAxisTime,
  formatHistoryEndLabel,
  getLatestPopulatedDay,
} from "./historySeries.js";

test("history series contains only one 15:00 value for each trading day", () => {
  const items = [
    {
      trade_date: "2026-09-03",
      time_points: ["09:30", "15:00"],
      series: [{ code: "BK1", name: "行业 A", latest_net_inflow: 2, data: [1, 2] }],
    },
    {
      trade_date: "2026-09-02",
      time_points: ["09:30", "15:00"],
      series: [{ code: "BK1", name: "行业 A", latest_net_inflow: 1, data: [0.5, 1] }],
    },
  ];
  const result = buildHistorySeries(items, items[0].series);

  assert.deepEqual(result.timePoints, ["2026-09-02 15:00", "2026-09-03 15:00"]);
  assert.equal(result.series.length, 1);
  assert.deepEqual(result.series[0].data, [1, 2]);
  assert.equal(formatHistoryAxisTime(result.timePoints[1]), "09-03\n15:00");
  assert.equal(getLatestPopulatedDay(items).trade_date, "2026-09-03");
});

test("history series forward-fills a missing trading-day close from the previous trading day", () => {
  const items = [
    { trade_date: "2026-09-04", time_points: ["15:00"], series: [{ code: "BK1", name: "行业 A", data: [3] }] },
    { trade_date: "2026-09-03", time_points: ["15:00"], series: [] },
    { trade_date: "2026-09-02", time_points: ["15:00"], series: [{ code: "BK1", name: "行业 A", data: [2] }] },
    { trade_date: "2026-09-01", time_points: ["15:00"], series: [] },
  ];
  const result = buildHistorySeries(items, [{ code: "BK1", name: "行业 A", latest_net_inflow: 3 }]);

  assert.deepEqual(result.timePoints, [
    "2026-09-01 15:00",
    "2026-09-02 15:00",
    "2026-09-03 15:00",
    "2026-09-04 15:00",
  ]);
  assert.deepEqual(result.series[0].data, [null, 2, 2, 3]);
});

test("period rankings preserve net totals for the highest and lowest ranked sectors", () => {
  const result = buildPeriodRankingSeries({
    inflows: [{ code: "A", name: "行业 A", inflow_total: 0, outflow_total: 1, net_inflow_total: -1 }],
    outflows: [
      { code: "B", name: "行业 B", inflow_total: 3.5, outflow_total: 0, net_inflow_total: 3.5 },
      { code: "C", name: "行业 C", inflow_total: 0, outflow_total: 4, net_inflow_total: -4 },
    ],
  });

  assert.deepEqual(result.inflows.map((item) => item.latest_net_inflow), [-1]);
  assert.deepEqual(result.outflows.map((item) => item.latest_net_inflow), [3.5, -4]);
  assert.deepEqual(result.series.map((item) => item.code), ["A", "B", "C"]);
});

test("history end labels show the sector and latest net inflow or outflow", () => {
  assert.equal(formatHistoryEndLabel("行业 A", 2), "行业 A +2.0亿");
  assert.equal(formatHistoryEndLabel("行业 B", -1.25), "行业 B -1.3亿");
});
