import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchSectorIntraday } from "./api/client";
import SectorFlowChart from "./components/SectorFlowChart";
import SectorRankingList from "./components/SectorRankingList";
import "./index.css";

const REQUEST_INFLOW_TOP = 25;
const REQUEST_OUTFLOW_TOP = 25;
const DEFAULT_INFLOW_TOP = 5;
const DEFAULT_OUTFLOW_TOP = 5;

function splitSeries(series) {
  return {
    inflows: series
      .filter((item) => item.latest_net_inflow > 0)
      .sort((a, b) => b.latest_net_inflow - a.latest_net_inflow),
    outflows: series
      .filter((item) => item.latest_net_inflow < 0)
      .sort((a, b) => a.latest_net_inflow - b.latest_net_inflow),
  };
}

function defaultSelectedCodes(series) {
  const { inflows, outflows } = splitSeries(series);
  return new Set([
    ...inflows.slice(0, DEFAULT_INFLOW_TOP).map((item) => item.code),
    ...outflows.slice(0, DEFAULT_OUTFLOW_TOP).map((item) => item.code),
  ]);
}

export default function App() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [errorMsg, setErrorMsg] = useState("");
  const [selectedCodes, setSelectedCodes] = useState(() => new Set());
  const selectedTradeDateRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const result = await fetchSectorIntraday({
        inflowTop: REQUEST_INFLOW_TOP,
        outflowTop: REQUEST_OUTFLOW_TOP,
      });
      setData(result);
      setStatus("ready");

      // 仅在首次获得某交易日的数据时默认选中两侧前五，不覆盖用户本次浏览的手动选择。
      if (result.series.length > 0 && selectedTradeDateRef.current !== result.trade_date) {
        selectedTradeDateRef.current = result.trade_date;
        setSelectedCodes(defaultSelectedCodes(result.series));
      }
    } catch (err) {
      setErrorMsg(err?.response?.data?.detail || err.message || "请求后端接口失败");
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    setStatus("loading");
    load();
  }, [load]);

  const toggleSeries = useCallback((code) => {
    setSelectedCodes((previous) => {
      const next = new Set(previous);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  }, []);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>行业板块资金流向监控</h1>
        <span className="subtitle">数据来自东方财富，仅供参考，不构成投资建议</span>
      </header>

      <div className="panel">
        <IntradayPanel
          data={data}
          errorMsg={errorMsg}
          onToggle={toggleSeries}
          selectedCodes={selectedCodes}
          status={status}
        />
      </div>

      <p className="footnote">
        数据来源：东方财富（未公开接口，逆向整理，字段随时可能变化）。仅供个人学习使用，请勿高频请求或用于商业分发。
      </p>
    </div>
  );
}

function IntradayPanel({ status, errorMsg, data, selectedCodes, onToggle }) {
  const rankings = useMemo(() => splitSeries(data?.series || []), [data?.series]);
  const chartData = useMemo(() => {
    if (!data) return null;
    return {
      ...data,
      series: data.series.filter((item) => selectedCodes.has(item.code)),
    };
  }, [data, selectedCodes]);

  if (status === "loading") {
    return <div className="state-message">加载中...</div>;
  }

  if (status === "error") {
    return (
      <div className="state-message error">
        加载失败：{errorMsg}
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
          {data.trade_date} · 东方财富行业板块 · 默认显示资金流入前 {DEFAULT_INFLOW_TOP} · 资金流出前 {DEFAULT_OUTFLOW_TOP}
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
