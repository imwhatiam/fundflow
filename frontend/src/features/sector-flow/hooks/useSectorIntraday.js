import { useEffect, useState } from "react";

import {
  fetchSectorIntraday,
  fetchSectorIntradayHistory,
} from "../../../api/client";
import { REQUEST_INFLOW_TOP, REQUEST_OUTFLOW_TOP } from "../constants";

function getErrorMessage(error) {
  return error?.response?.data?.detail || error?.message || "请求后端接口失败";
}

/** 单日请求原分时接口，多日请求固定交易日窗口的收盘接口。 */
export function useSectorIntraday(date, historyDays) {
  const [data, setData] = useState([]);
  const [periodRankings, setPeriodRankings] = useState({ inflows: [], outflows: [] });
  const [status, setStatus] = useState("loading");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let isCurrentRequest = true;

    async function load() {
      setStatus("loading");
      setErrorMessage("");
      setPeriodRankings({ inflows: [], outflows: [] });

      try {
        if (historyDays === 1) {
          const result = await fetchSectorIntraday({
            date,
            inflowTop: REQUEST_INFLOW_TOP,
            outflowTop: REQUEST_OUTFLOW_TOP,
          });
          if (!isCurrentRequest) {
            return;
          }
          setData([result]);
          setPeriodRankings({ inflows: [], outflows: [] });
        } else {
          const result = await fetchSectorIntradayHistory({
            date,
            days: historyDays,
            inflowTop: REQUEST_INFLOW_TOP,
            outflowTop: REQUEST_OUTFLOW_TOP,
          });
          if (!isCurrentRequest) {
            return;
          }
          setData(result.items || []);
          setPeriodRankings(result.period_rankings || { inflows: [], outflows: [] });
        }
        setStatus("ready");
      } catch (error) {
        if (!isCurrentRequest) {
          return;
        }
        setErrorMessage(getErrorMessage(error));
        setStatus("error");
      }
    }

    load();
    return () => {
      isCurrentRequest = false;
    };
  }, [date, historyDays]);

  return { data, errorMessage, periodRankings, status };
}
