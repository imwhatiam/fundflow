const TABS = [
  { key: "intraday", label: "当日走势" },
  { key: "multiday", label: "多日累计" },
  { key: "netAmount", label: "主力净额" },
  { key: "relativeFlow", label: "相对流入" },
  { key: "changePct", label: "涨跌幅" },
];

/**
 * 顶部 Tab 栏，样式对应截图。目前后端只实现了"当日走势"，
 * 其它 tab 先展示占位提示，不假装已经支持。
 */
export default function TabBar({ activeTab, onChange, category, onCategoryChange }) {
  return (
    <div className="tab-bar">
      {TABS.map((tab) => (
        <button
          key={tab.key}
          className={tab.key === activeTab ? "active" : ""}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
      <div className="spacer" />
      <div className="category-switch">
        <button
          className={category === "industry" ? "active" : ""}
          onClick={() => onCategoryChange("industry")}
        >
          行业板块
        </button>
        <button
          className={category === "concept" ? "active" : ""}
          onClick={() => onCategoryChange("concept")}
        >
          概念板块
        </button>
      </div>
    </div>
  );
}
