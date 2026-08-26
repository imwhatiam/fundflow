import axios from "axios";

// 开发环境默认指向本地 Django (manage.py runserver 默认端口 8000)。
// 生产部署时通过构建环境变量 VITE_API_BASE 覆盖。
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api";
const SECTOR_INTRADAY_CACHE_PREFIX = "fundflow:sector-intraday";
const SECTOR_INTRADAY_CACHE_TTL_MS = 45_000;

const client = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
});

function sectorIntradayCacheKey({ date, inflowTop, outflowTop }) {
  return `${SECTOR_INTRADAY_CACHE_PREFIX}:${date || "latest"}:${inflowTop}:${outflowTop}`;
}

function readSectorIntradayCache(key) {
  try {
    const cached = JSON.parse(window.localStorage.getItem(key));
    if (!cached || !cached.data || !Number.isFinite(cached.cachedAt)) return null;
    if (Date.now() - cached.cachedAt > SECTOR_INTRADAY_CACHE_TTL_MS) return null;
    return cached.data;
  } catch {
    return null;
  }
}

function writeSectorIntradayCache(key, data) {
  try {
    window.localStorage.setItem(key, JSON.stringify({ cachedAt: Date.now(), data }));
  } catch {
    // 隐私模式、禁用存储或配额已满时仍允许正常从网络读取数据。
  }
}

/**
 * 板块分时累计主力净流入曲线（对应“当日走势”）。
 * 同一组 Top N 结果在浏览器中缓存 45 秒，避免页面轮询重复请求后端。
 * @param {{date?: string, inflowTop?: number, outflowTop?: number}} params
 */
export async function fetchSectorIntraday({ date, inflowTop = 5, outflowTop = 5 } = {}) {
  const params = {
    inflow_top: inflowTop,
    outflow_top: outflowTop,
  };
  if (date) params.date = date;

  const cacheKey = sectorIntradayCacheKey({ date, inflowTop, outflowTop });
  const cached = readSectorIntradayCache(cacheKey);
  if (cached) return cached;

  const { data } = await client.get("/sectors/intraday/", { params });
  writeSectorIntradayCache(cacheKey, data);
  return data;
}

/** 板块列表 */
export async function fetchSectors() {
  const { data } = await client.get("/sectors/");
  return data;
}

export default client;
