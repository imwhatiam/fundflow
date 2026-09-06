import { useEffect, useState } from "react";

import DateRangeControls from "./components/DateRangeControls";
import { fetchTradingDay } from "./api/client";
import KaipanlaFlowPage from "./features/kaipanla-flow/KaipanlaFlowPage";
import SectorFlowPage from "./features/sector-flow/SectorFlowPage";
import { formatLocalDate } from "./lib/localDate";
import "./index.css";

const TABS = [
  { key: "kaipanla", label: "开盘啦" },
  { key: "eastmoney", label: "东方财富" },
];

/** 应用根组件：两个独立数据源通过 tab 切换，默认进入开盘啦。 */
export default function App() {
  const today = formatLocalDate(new Date());
  const [activeTab, setActiveTab] = useState("kaipanla");
  /** 最近一个 A 股交易日：今天不是交易日时，由服务端回退得到。 */
  const [latestTradeDate, setLatestTradeDate] = useState(today);
  const [selectedDate, setSelectedDate] = useState(today);
  const [historyDays, setHistoryDays] = useState(1);

  useEffect(() => {
    let active = true;
    fetchTradingDay({ date: today })
      .then((data) => {
        if (!active || !data?.date) return;
        setLatestTradeDate(data.date);
        // 进入页面时若当天不是交易日，直接落到最近一个交易日。
        setSelectedDate((current) => (current === today ? data.date : current));
      })
      .catch(() => {
        // 交易日历不可用时保持当天，不阻塞页面渲染。
      });
    return () => {
      active = false;
    };
  }, [today]);

  const handleDateChange = (date) => {
    setSelectedDate(date);
    setHistoryDays(1);
  };

  const handleToday = () => {
    setSelectedDate(latestTradeDate);
    setHistoryDays(1);
  };

  const handleHistoryDaysChange = (days) => {
    setSelectedDate(latestTradeDate);
    setHistoryDays(days);
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>板块资金流向监控</h1>
        <span className="subtitle">
          {`东方财富 / 开盘啦，仅供参考，不构成投资建议。${
            activeTab === "eastmoney" ? "东方财富获取数据时可能有延迟或失败。" : ""
          }`}
        </span>
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
        latestTradeDate={latestTradeDate}
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
    </div>
  );
}
