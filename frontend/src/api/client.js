import axios from "axios";

// 开发环境默认指向本地 Django (manage.py runserver 默认端口 8000)。
// 生产部署时通过构建环境变量 VITE_API_BASE 覆盖（只填协议+主机，不含数据源前缀）。
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const client = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
});

/**
 * 东财板块分时累计主力净流入曲线（对应“当日走势”）。
 * 每次调用都请求服务端；服务端负责按交易刻度缓存聚合结果。
 * @param {{date?: string, inflowTop?: number, outflowTop?: number}} params
 */
export async function fetchSectorIntraday({ date, inflowTop = 5, outflowTop = 5 } = {}) {
  const params = {
    inflow_top: inflowTop,
    outflow_top: outflowTop,
  };
  if (date) params.date = date;

  const { data } = await client.get("/eastmoney-api/sectors/intraday/", { params });
  return data;
}

/** 东财板块列表 */
export async function fetchSectors() {
  const { data } = await client.get("/eastmoney-api/sectors/");
  return data;
}

/**
 * 开盘啦板块分时累计主力净流入曲线。
 * 与东财完全独立，走独立的 /kaipanla-api/ 接口。
 * @param {{date?: string, inflowTop?: number, outflowTop?: number}} params
 */
export async function fetchKaipanlaIntraday({ date, inflowTop = 5, outflowTop = 5 } = {}) {
  const params = {
    inflow_top: inflowTop,
    outflow_top: outflowTop,
  };
  if (date) params.date = date;

  const { data } = await client.get("/kaipanla-api/sectors/intraday/", { params });
  return data;
}

/** 开盘啦板块列表 */
export async function fetchKaipanlaSectors() {
  const { data } = await client.get("/kaipanla-api/sectors/");
  return data;
}

export default client;
