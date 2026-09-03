# 行业板块资金流向监控 · 前端 (React + ECharts)

## 快速开始

```bash
npm install
npm run dev
```

默认会请求 `http://localhost:8000`（对应 Django 后端 `manage.py runserver 8000`）。
如果后端跑在别的地址，新建 `.env.local`：

```
VITE_API_BASE=http://your-backend-host:8000
```

## 生产构建

```bash
npm run build
```

产物在 `dist/`，是纯静态文件，可以用 Nginx 直接托管，或者跟 Django 一起部署（Nginx 反代 `/eastmoney-api/`、`/kaipanla-api/` 到 Django，其它路径走 `dist/`）。

## 页面范围

两个数据源 tab：**东方财富**（默认）与**开盘啦**，各自展示板块当日分时累计净流入曲线。页面加载时请求数据，刷新页面后再次获取。
