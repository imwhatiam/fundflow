const HISTORY_DAY_OPTIONS = [5, 10, 20];

/** 选择结束日期，并切换要显示的交易日数量。 */
export default function DateRangeControls({
  date,
  historyDays,
  maxDate,
  onDateChange,
  onHistoryDaysChange,
  onToday,
}) {
  return (
    <section className="date-range-controls" aria-label="日期和历史数据范围">
      <label className="date-picker-label" htmlFor="trade-date">
        <input
          aria-label="结束日期"
          id="trade-date"
          max={maxDate}
          onChange={(event) => onDateChange(event.target.value)}
          type="date"
          value={date}
        />
      </label>
      <div className="history-day-buttons" aria-label="查询范围">
        <button
          aria-pressed={historyDays === 1 && date === maxDate}
          className={`history-day-button ${historyDays === 1 && date === maxDate ? "active" : ""}`}
          onClick={onToday}
          type="button"
        >
          当日
        </button>
        {HISTORY_DAY_OPTIONS.map((days) => (
          <button
            aria-pressed={historyDays === days}
            className={`history-day-button ${historyDays === days ? "active" : ""}`}
            key={days}
            onClick={() => onHistoryDaysChange(days)}
            type="button"
          >
            {days}天
          </button>
        ))}
      </div>
    </section>
  );
}
