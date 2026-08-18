import { useCallback, useEffect, useState } from "react";
import TabBar from "./components/TabBar";
import SectorFlowChart from "./components/SectorFlowChart";
import { fetchSectorIntraday } from "./api/client";
import "./index.css";

const POLL_INTERVAL_MS = 30000; // 交易时段内每30秒轮询一次；后端自身也有缓存(45s)兜底

export default function App() {
  const [activeTab, setActiveTab] = useState("intraday");
  const [category, setCategory] = useState("industry");
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [errorMsg, setErrorMsg] = useState("");

  const load = useCallback(async () => {
    try {
      const result = await fetchSectorIntraday({ category, top: 10 });
      setData(result);
      setStatus("ready");
    } catch (err) {
      setErrorMsg(err?.response?.data?.detail || err.message || "请求后端接口失败");
      setStatus("error");
    }
  }, [category]);

  useEffect(() => {
    setStatus("loading");
    load();

    if (activeTab !== "intraday") return undefined;

    const timer = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [load, activeTab]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>板块资金流向监控</h1>
        <span className="subtitle">数据来自东方财富，仅供参考，不构成投资建议</span>
      </header>

      <div className="panel">
        <TabBar
          activeTab={activeTab}
          onChange={setActiveTab}
          category={category}
          onCategoryChange={setCategory}
        />

        {activeTab !== "intraday" ? (
          <div className="placeholder-tab">这个 tab 还没接后端数据，敬请期待</div>
        ) : (
          <IntradayPanel status={status} errorMsg={errorMsg} data={data} category={category} />
        )}
      </div>

      <p className="footnote">
        数据来源：东方财富（未公开接口，逆向整理，字段随时可能变化）。仅供个人学习使用，请勿高频请求或用于商业分发。
      </p>
    </div>
  );
}

function IntradayPanel({ status, errorMsg, data, category }) {
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
        今天还没有数据。请确认 crontab 里的 fetch_stock_fund_flow / sync_sectors 命令已经跑过至少一次。
      </div>
    );
  }

  return (
    <>
      <div className="chart-meta">
        <span>
          {data.trade_date} · {category === "industry" ? "行业板块" : "概念板块"} · Top {data.series.length}
        </span>
        {data.stale && <span className="stale-badge">数据可能不是最新</span>}
      </div>
      <div className="chart-area">
        <SectorFlowChart data={data} />
      </div>
    </>
  );
}
