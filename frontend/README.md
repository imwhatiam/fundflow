# 板块资金流向监控 · 前端 (React + ECharts)

## 快速开始

```bash
npm install
npm run dev
```

默认会请求 `http://localhost:8000/api`（对应 Django 后端 `manage.py runserver 8000`）。
如果后端跑在别的地址，新建 `.env.local`：

```
VITE_API_BASE=http://your-backend-host:8000/api
```

## 生产构建

```bash
npm run build
```

产物在 `dist/`，是纯静态文件，可以用 Nginx 直接托管，或者跟 Django 一起部署（Nginx 反代 `/api` 到 Django，其它路径走 `dist/`）。

## 目前的实现范围

只完整实现了顶部 tab 里的**"当日走势"**（板块分时累计净流入曲线，行业/概念板块可切换）。
其它几个 tab（多日累计、主力净额等）是占位状态，还没接后端数据。
