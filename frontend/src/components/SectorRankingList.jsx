function formatFlow(value) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}亿`;
}

/** 允许用户选择是否在上方图表展示的 Top 25 板块列表。 */
export default function SectorRankingList({ direction, series, selectedCodes, onToggle }) {
  const isInflow = direction === "inflow";
  const title = isInflow ? "资金流入前 25" : "资金流出前 25";
  const amountClass = isInflow ? "inflow-amount" : "outflow-amount";

  return (
    <section className={`ranking-column ${direction}`} aria-label={title}>
      <h2>{title}</h2>
      <div className="ranking-list">
        {series.map((item, index) => (
          <label className="ranking-row" key={item.code}>
            <input
              aria-label={`在图表中显示${item.name}`}
              checked={selectedCodes.has(item.code)}
              className="ranking-checkbox"
              onChange={() => onToggle(item.code)}
              type="checkbox"
            />
            <span className="ranking-rank">{index + 1}</span>
            <span className="ranking-name" title={item.name}>{item.name}</span>
            <span className={`ranking-amount ${amountClass}`}>{formatFlow(item.latest_net_inflow)}</span>
          </label>
        ))}
      </div>
    </section>
  );
}
