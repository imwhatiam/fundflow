import { useMemo } from "react";

import SectorFlowChart from "../../components/SectorFlowChart";
import SectorRankingList from "../../components/SectorRankingList";
import {
  DEFAULT_INFLOW_TOP,
  DEFAULT_OUTFLOW_TOP,
} from "./constants";
import { useSectorIntraday } from "./hooks/useSectorIntraday";
import { useSelectedSectorCodes } from "./hooks/useSelectedSectorCodes";
import { getSelectedSeries, splitSeriesByDirection } from "./lib/series";

/** 三级行业资金流页面：组合请求、勾选和展示组件。 */
export default function SectorFlowPage() {
  const { data, errorMessage, status } = useSectorIntraday();
  const series = useMemo(() => data?.series || [], [data]);
  const { selectedCodes, toggleSelectedCode } = useSelectedSectorCodes(
    data?.trade_date,
    series,
  );

  const rankings = useMemo(() => splitSeriesByDirection(series), [series]);
  const chartData = useMemo(() => {
    if (!data) {
      return null;
    }

    return {
      ...data,
      series: getSelectedSeries(series, selectedCodes),
    };
  }, [data, selectedCodes, series]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>三级行业资金流向监控</h1>
        <span className="subtitle">数据来自东方财富，仅供参考，不构成投资建议</span>
      </header>

      <main className="panel">
        <SectorFlowContent
          chartData={chartData}
          data={data}
          errorMessage={errorMessage}
          rankings={rankings}
          selectedCodes={selectedCodes}
          status={status}
          onToggle={toggleSelectedCode}
        />
      </main>

      <p className="footnote">
        数据来源：东方财富（未公开接口，逆向整理，字段随时可能变化）。仅供个人学习使用，请勿高频请求或用于商业分发。
      </p>
    </div>
  );
}

function SectorFlowContent({
  chartData,
  data,
  errorMessage,
  rankings,
  selectedCodes,
  status,
  onToggle,
}) {
  if (status === "loading") {
    return <div className="state-message">加载中...</div>;
  }

  if (status === "error") {
    return (
      <div className="state-message error">
        加载失败：{errorMessage}
        <br />
        请确认后端服务已启动（默认 http://localhost:8000 ，可通过 VITE_API_BASE 修改）
      </div>
    );
  }

  if (!data || data.series.length === 0) {
    return (
      <div className="state-message">
        今天还没有数据。请确认 crontab 里的 fetch_sector_fund_flow 命令已经跑过至少一次。
      </div>
    );
  }

  return (
    <>
      <div className="chart-meta">
        <span>
          {data.trade_date} · 东方财富三级行业 · 默认显示资金流入前 {DEFAULT_INFLOW_TOP} · 资金流出前 {DEFAULT_OUTFLOW_TOP}
        </span>
        {data.stale && <span className="stale-badge">数据可能不是最新</span>}
      </div>
      <div className="chart-area">
        <SectorFlowChart data={chartData} />
      </div>
      <div className="rankings">
        <SectorRankingList
          direction="inflow"
          onToggle={onToggle}
          selectedCodes={selectedCodes}
          series={rankings.inflows}
        />
        <SectorRankingList
          direction="outflow"
          onToggle={onToggle}
          selectedCodes={selectedCodes}
          series={rankings.outflows}
        />
      </div>
    </>
  );
}
