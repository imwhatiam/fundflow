import { useCallback, useEffect, useState } from "react";

import { fetchSectorIntraday } from "../../../api/client";
import { REQUEST_INFLOW_TOP, REQUEST_OUTFLOW_TOP } from "../constants";

function getErrorMessage(error) {
  return error?.response?.data?.detail || error?.message || "请求后端接口失败";
}

/** 负责调用分时接口，并暴露清晰的加载、成功和失败状态。 */
export function useSectorIntraday() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("loading");
  const [errorMessage, setErrorMessage] = useState("");

  const load = useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");

    try {
      const result = await fetchSectorIntraday({
        inflowTop: REQUEST_INFLOW_TOP,
        outflowTop: REQUEST_OUTFLOW_TOP,
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
