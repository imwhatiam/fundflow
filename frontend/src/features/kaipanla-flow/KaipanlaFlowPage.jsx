import { useMemo } from "react";

import SectorFlowChart from "../../components/SectorFlowChart";
import SectorRankingList from "../../components/SectorRankingList";
import {
  KPL_DEFAULT_INFLOW_TOP,
  KPL_DEFAULT_OUTFLOW_TOP,
} from "./constants";
import { useKaipanlaIntraday } from "./hooks/useKaipanlaIntraday";
import { useKaipanlaSelectedSectorCodes } from "./hooks/useKaipanlaSelectedSectorCodes";
import { getKaipanlaSelectedSeries, splitKaipanlaSeriesByDirection } from "./lib/series";

/** 开盘啦板块资金流页面：组合请求、勾选和展示组件。 */
export default function KaipanlaFlowPage() {
  const { data, errorMessage, status } = useKaipanlaIntraday();
  const series = useMemo(() => data?.series || [], [data]);
  const { selectedCodes, toggleSelectedCode } = useKaipanlaSelectedSectorCodes(
    data?.trade_date,
    series,
  );

  const rankings = useMemo(() => splitKaipanlaSeriesByDirection(series), [series]);
  const chartData = useMemo(() => {
    if (!data) {
      return null;
    }

    return {
      ...data,
      series: getKaipanlaSelectedSeries(series, selectedCodes),
    };
  }, [data, selectedCodes, series]);

  return (
    <main className="panel">
      <KaipanlaFlowContent
        chartData={chartData}
        data={data}
        errorMessage={errorMessage}
        rankings={rankings}
        selectedCodes={selectedCodes}
        status={status}
        onToggle={toggleSelectedCode}
      />
    </main>
  );
}

function KaipanlaFlowContent({
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
        今天还没有开盘啦数据。请确认 crontab 里的 fetch_kaipanla_sector_fund_flow 命令已经跑过至少一次。
      </div>
    );
  }

  return (
    <>
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
