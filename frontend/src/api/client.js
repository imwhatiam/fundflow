import axios from "axios";

// 开发环境默认指向本地 Django (manage.py runserver 默认端口 8000)。
// 生产部署时通过构建环境变量 VITE_API_BASE 覆盖。
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api";

const client = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
});

/**
 * 板块分时累计主力净流入曲线（对应"当日走势"tab）。
 * @param {{date?: string, inflowTop?: number, outflowTop?: number}} params
 */
export async function fetchSectorIntraday({ date, inflowTop = 5, outflowTop = 5 } = {}) {
  const params = {
    inflow_top: inflowTop,
    outflow_top: outflowTop,
  };
  if (date) params.date = date;
  const { data } = await client.get("/sectors/intraday/", { params });
  return data;
}

/** 板块列表 */
export async function fetchSectors() {
  const { data } = await client.get("/sectors/");
  return data;
}

/** 单只个股当日分时曲线 */
export async function fetchStockIntraday(code, { date } = {}) {
  const params = {};
  if (date) params.date = date;
  const { data } = await client.get(`/stocks/${code}/intraday/`, { params });
  return data;
}

export default client;
