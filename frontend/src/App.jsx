import { useState } from "react";

import KaipanlaFlowPage from "./features/kaipanla-flow/KaipanlaFlowPage";
import SectorFlowPage from "./features/sector-flow/SectorFlowPage";
import "./index.css";

const TABS = [
  { key: "eastmoney", label: "东方财富" },
  { key: "kaipanla", label: "开盘啦" },
];

/** 应用根组件：两个独立数据源通过 tab 切换，默认进入东方财富。 */
export default function App() {
  const [activeTab, setActiveTab] = useState("eastmoney");

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>板块资金流向监控</h1>
        <span className="subtitle">东方财富 / 开盘啦，仅供参考，不构成投资建议</span>
      </header>

      <nav className="source-tabs" aria-label="数据源">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={`source-tab ${activeTab === tab.key ? "active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === "eastmoney" ? <SectorFlowPage /> : <KaipanlaFlowPage />}

      <p className="footnote">
        东方财富数据来自未公开接口，开盘啦数据来自 apphwshhq.longhuvip.com。仅供个人学习使用，请勿高频请求或用于商业分发。
      </p>
    </div>
  );
}
