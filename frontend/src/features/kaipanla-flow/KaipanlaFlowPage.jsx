import { useMemo } from "react";

import SectorFlowChart from "../../components/SectorFlowChart";
import SectorFlowHistoryChart from "../../components/SectorFlowHistoryChart";
import SectorRankingList from "../../components/SectorRankingList";
import {
  buildPeriodRankingSeries,
  getLatestPopulatedDay,
} from "../../lib/historySeries";
import {
  KPL_DEFAULT_INFLOW_TOP,
  KPL_DEFAULT_OUTFLOW_TOP,
} from "./constants";
import { useKaipanlaIntraday } from "./hooks/useKaipanlaIntraday";
import { useKaipanlaSelectedSectorCodes } from "./hooks/useKaipanlaSelectedSectorCodes";
import { getKaipanlaSelectedSeries, splitKaipanlaSeriesByDirection } from "./lib/series";

/** 开盘啦板块资金流页面：展示单日或多个交易日的分时数据。 */
export default function KaipanlaFlowPage({ date, historyDays }) {
  const { data, errorMessage, periodRankings, status } = useKaipanlaIntraday(date, historyDays);
  const latestPopulatedDay = useMemo(() => getLatestPopulatedDay(data), [data]);

  if (status === "loading" && data.length === 0) {
    return <main className="panel"><div className="state-message">加载中...</div></main>;
  }

  if (status === "error") {
    return (
      <main className="panel">
        <div className="state-message error">
          加载失败：{errorMessage}
          <br />
          请确认后端服务已启动（默认 http://localhost:8000 ，可通过 VITE_API_BASE 修改）
        </div>
      </main>
    );
  }

  if (!latestPopulatedDay) {
    return (
      <main className="panel">
        <div className="state-message">
          截至 {date} 还没有开盘啦数据。请确认 crontab 里的 fetch_kaipanla_sector_fund_flow 命令已经跑过至少一次。
        </div>
      </main>
    );
  }

  if (historyDays > 1) {
    return <KaipanlaFlowHistory
      data={data}
      historyDays={historyDays}
      latestDay={latestPopulatedDay}
      periodRankings={periodRankings}
    />;
  }

  return <KaipanlaFlowDay data={latestPopulatedDay} />;
}

function KaipanlaFlowHistory({ data, latestDay, historyDays, periodRankings }) {
  const { inflows, outflows, series } = useMemo(
    () => buildPeriodRankingSeries(periodRankings),
    [periodRankings],
  );
  const { selectedCodes, toggleSelectedCode } = useKaipanlaSelectedSectorCodes(
    `${latestDay.trade_date}:${historyDays}`,
    series,
  );
  const selectedSeries = useMemo(
    () => getKaipanlaSelectedSeries(series, selectedCodes),
    [series, selectedCodes],
  );
  const stale = data.some((item) => item.stale);

  return (
    <main className="history-panel">
      <section className="panel history-day" aria-label="开盘啦板块历史数据">
        <div className="chart-meta">
          <span>开盘啦板块历史走势</span>
          {stale && <span className="stale-badge">数据可能不是最新</span>}
        </div>
        <div className="chart-area">
          <SectorFlowHistoryChart
            items={data}
            series={selectedSeries}
          />
        </div>
        <div className="rankings">
          <SectorRankingList
            direction="inflow"
            onToggle={toggleSelectedCode}
            selectedCodes={selectedCodes}
            series={inflows}
          />
          <SectorRankingList
            direction="outflow"
            onToggle={toggleSelectedCode}
            selectedCodes={selectedCodes}
            series={outflows}
          />
        </div>
      </section>
    </main>
  );
}

function KaipanlaFlowDay({ data }) {
  const series = useMemo(() => data.series || [], [data]);
  const { selectedCodes, toggleSelectedCode } = useKaipanlaSelectedSectorCodes(
    data.trade_date,
    series,
  );
  const rankings = useMemo(() => splitKaipanlaSeriesByDirection(series), [series]);
  const chartData = useMemo(() => ({
    ...data,
    series: getKaipanlaSelectedSeries(series, selectedCodes),
  }), [data, selectedCodes, series]);

  return (
    <main className="history-panel">
      <section className="panel history-day" aria-label={`${data.trade_date} 开盘啦板块数据`}>
        <div className="chart-meta">
          <span>
            {data.trade_date} · 开盘啦板块 · 默认显示资金流入前 {KPL_DEFAULT_INFLOW_TOP} · 资金流出前 {KPL_DEFAULT_OUTFLOW_TOP}
          </span>
          {data.stale && <span className="stale-badge">数据可能不是最新</span>}
        </div>
        <div className="chart-area">
          <SectorFlowChart data={chartData} />
        </div>
        <div className="rankings">
          <SectorRankingList
            direction="inflow"
            onToggle={toggleSelectedCode}
            selectedCodes={selectedCodes}
            series={rankings.inflows}
          />
          <SectorRankingList
            direction="outflow"
            onToggle={toggleSelectedCode}
            selectedCodes={selectedCodes}
            series={rankings.outflows}
          />
        </div>
      </section>
    </main>
  );
}
