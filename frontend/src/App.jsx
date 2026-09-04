import { useState } from "react";

import DateRangeControls from "./components/DateRangeControls";
import KaipanlaFlowPage from "./features/kaipanla-flow/KaipanlaFlowPage";
import SectorFlowPage from "./features/sector-flow/SectorFlowPage";
import { formatLocalDate } from "./lib/localDate";
import "./index.css";

const TABS = [
  { key: "eastmoney", label: "东方财富" },
  { key: "kaipanla", label: "开盘啦" },
];

/** 应用根组件：两个独立数据源通过 tab 切换，默认进入东方财富。 */
export default function App() {
  const today = formatLocalDate(new Date());
  const [activeTab, setActiveTab] = useState("eastmoney");
  const [selectedDate, setSelectedDate] = useState(today);
  const [historyDays, setHistoryDays] = useState(1);

  const handleDateChange = (date) => {
    setSelectedDate(date);
    setHistoryDays(1);
  };

  const handleToday = () => {
    setSelectedDate(today);
    setHistoryDays(1);
  };

  const handleHistoryDaysChange = (days) => {
    setSelectedDate(today);
    setHistoryDays(days);
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>板块资金流向监控</h1>
        <span className="subtitle">东方财富 / 开盘啦，仅供参考，不构成投资建议</span>
      </header>

      <nav className="source-tabs" aria-label="数据源">
        {TABS.map((tab) => (
          <button
            aria-pressed={activeTab === tab.key}
            key={tab.key}
            type="button"
            className={`source-tab ${activeTab === tab.key ? "active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <DateRangeControls
        date={selectedDate}
        historyDays={historyDays}
        maxDate={today}
        onDateChange={handleDateChange}
        onHistoryDaysChange={handleHistoryDaysChange}
        onToday={handleToday}
      />

      {activeTab === "eastmoney" ? (
        <SectorFlowPage date={selectedDate} historyDays={historyDays} />
      ) : (
        <KaipanlaFlowPage date={selectedDate} historyDays={historyDays} />
      )}

      <p className="footnote">
        东方财富数据来自未公开接口，开盘啦数据来自 apphwshhq.longhuvip.com。仅供个人学习使用，请勿高频请求或用于商业分发。
      </p>
    </div>
  );
}
