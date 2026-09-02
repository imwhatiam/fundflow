import { useCallback, useEffect, useRef, useState } from "react";

import { DEFAULT_INFLOW_TOP, DEFAULT_OUTFLOW_TOP } from "../constants";
import { getDefaultSelectedCodes } from "../lib/series";

/**
 * 保存图表勾选状态。
 * 同一交易日不覆盖手动勾选；切换到有数据的新交易日才恢复默认选中项。
 */
export function useSelectedSectorCodes(tradeDate, series) {
  const [selectedCodes, setSelectedCodes] = useState(() => new Set());
  const selectedTradeDateRef = useRef(null);

  useEffect(() => {
    if (!tradeDate || series.length === 0) {
      return;
    }
    if (selectedTradeDateRef.current === tradeDate) {
      return;
    }

    selectedTradeDateRef.current = tradeDate;
    setSelectedCodes(
      getDefaultSelectedCodes(series, DEFAULT_INFLOW_TOP, DEFAULT_OUTFLOW_TOP),
    );
  }, [series, tradeDate]);

  const toggleSelectedCode = useCallback((code) => {
    setSelectedCodes((previousCodes) => {
      const nextCodes = new Set(previousCodes);
      if (nextCodes.has(code)) {
        nextCodes.delete(code);
      } else {
        nextCodes.add(code);
      }
      return nextCodes;
    });
  }, []);

  return { selectedCodes, toggleSelectedCode };
}
