import { useCallback, useEffect, useState } from "react";

import { fetchKaipanlaIntraday } from "../../../api/client";
import { KPL_REQUEST_INFLOW_TOP, KPL_REQUEST_OUTFLOW_TOP } from "../constants";

function getErrorMessage(error) {
  return error?.response?.data?.detail || error?.message || "请求后端接口失败";
}

/** 负责调用开盘啦分时接口，并暴露清晰的加载、成功和失败状态。 */
export function useKaipanlaIntraday() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("loading");
  const [errorMessage, setErrorMessage] = useState("");

  const load = useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");

    try {
      const result = await fetchKaipanlaIntraday({
        inflowTop: KPL_REQUEST_INFLOW_TOP,
        outflowTop: KPL_REQUEST_OUTFLOW_TOP,
      });
      setData(result);
      setStatus("ready");
    } catch (error) {
      setErrorMessage(getErrorMessage(error));
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { data, errorMessage, status };
}
