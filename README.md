# 行业板块资金流向监控系统

一个面向 A 股盘中观察的 Django/React 工具。它定时抓取东方财富行业板块的累计主力资金流快照，按 15 分钟刻度保存，并在网页中展示资金流入、流出最显著的板块。数据仅供学习和内部研究，不构成投资建议；上游为未公开接口，字段、限流策略和可用性都可能变化。

![当日走势效果预览](docs/preview_intraday.png)

## 功能与数据流

```text
东方财富行业板块 clist/get（约 500 个 BKxxxx 板块）
        │ 分页请求，每页最多 200 条；每次成功请求后等待 10 秒
        ▼
fetch_sector_fund_flow
        │ 校验完整分页结果，映射到最近 15 分钟交易刻度
        ▼
EastmoneySectorFundFlowSnapshot（数据库）
        │ 聚合、缓存、Top N 筛选与缺失刻度前向填充
        ▼
GET /api/sectors/intraday/ ── React + ECharts
```

系统时区固定为 `Asia/Shanghai`。标准交易刻度为上午 `09:30–11:30`、下午 `13:00–15:00`，共 18 个点；例如 09:35 执行写入 09:30，10:10 执行写入 10:00。图表横轴始终显示 `09:30–15:00`，每 15 分钟一个刻度。

交易日判断使用 `chinese-calendar`，并额外排除所有周末，因此法定节假日、午休和调休周末不会正常抓取。交易所临时休市等法定日历以外的例外，需在部署时另行维护。

## 代码实现

### 目录职责

```text
backend/
├── config/                         # Django 配置、URL、WSGI/ASGI 入口
└── fundflow/
    ├── management/commands/
    │   └── fetch_sector_fund_flow.py
    ├── migrations/                 # 数据库结构演进记录
    ├── services/
    │   ├── eastmoney_client.py     # 上游请求、重试、分页与字段清洗
    │   ├── aggregation.py          # 分时聚合、Top N 与服务端缓存
    │   ├── trading_calendar.py     # A 股交易日判断
    │   └── trading_time.py         # 15 分钟刻度和交易时段
    ├── models.py                   # EastmoneySectorFundFlowSnapshot
    ├── views.py                    # 薄 API 视图
    └── urls.py
frontend/src/
├── api/client.js                   # Axios 与浏览器 localStorage 缓存
├── components/
│   ├── SectorFlowChart.jsx         # ECharts 图表
│   └── SectorRankingList.jsx       # 流入/流出 Top 25 选择列表
└── App.jsx                          # 轮询、默认选中与页面状态
```

### 抓取、落库与时间对齐

`EastmoneyClient` 只请求行业板块接口。它按接口返回的 `total` 和**实际返回条数**决定是否继续翻页；中间页失败、提前空页或出现重复板块代码时，整次抓取返回空结果，管理命令不会写入半份快照。若个别记录缺少必需字段，会跳过该记录、以 `WARNING` 日志记录丢弃数量，并继续写入其余有效行业。每个成功的上游请求（包括最后一页）都会 `sleep(10)`；连接或 JSON 错误最多重试 5 次，并使用指数退避。

`fetch_sector_fund_flow` 是唯一的抓取命令：

```bash
cd backend
python manage.py fetch_sector_fund_flow            # 仅交易时段抓取
python manage.py fetch_sector_fund_flow --dry-run  # 请求和打印，不写库
python manage.py fetch_sector_fund_flow --latest   # 非交易时段按东财最新行情初始化/恢复
```

正常命令在非交易时段直接退出。`--latest` 优先使用上游字段 `f124` 的行情时间，并向下对齐到最近合法刻度；例如上游收盘后返回 15:30 时，数据写入当日 15:00。`EastmoneySectorFundFlowSnapshot` 以 `(sector_code, snapshot_time)` 唯一约束保证同一快照可重复执行而不会产生重复行。

### API、缓存与前端显示

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/sectors/` | 某日最新刻度的板块代码与名称；日期省略时使用最近有数据的日期。 |
| `GET` | `/api/sectors/intraday/?date=2026-08-26&inflow_top=25&outflow_top=25` | 分时累计主力净流入曲线。`date` 可省略；两侧数量默认 5、范围 0–30。 |

`aggregate_sector_intraday()` 从快照表读取已到达的交易刻度，缺失点用该板块前一个已知累计值填充，并以 `stale` 标记不完整数据。它分别选择正值 Top N 和负值 Top N；金额从元转换为亿元。服务端缓存键包含交易日、最新刻度、数据版本和 Top N：当前交易日缓存到**下一个有效交易刻度**（午间会到 13:00），历史数据缓存两天；成功写入新快照后会更新数据版本。

前端一次请求流入、流出各 25 条，响应在浏览器 `localStorage` 缓存 45 秒，页面每 30 秒轮询但不会重复打到后端。进入页面时图表只默认勾选两侧前 5 条；下方两个 Top 25 列表可通过复选框增删图表曲线，流入金额为红色、流出金额为绿色。

## 本地开发

### 后端

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py fetch_sector_fund_flow --dry-run
python manage.py runserver 8000
```

### 前端

```bash
cd frontend
npm ci
npm run dev
```

开发环境前端默认访问 `http://localhost:8000/api`。如果后端地址不同，创建 `frontend/.env.local`：

```dotenv
VITE_API_BASE=http://127.0.0.1:8000/api
```

## 生产环境部署（Linux + Nginx + Gunicorn + PostgreSQL + Redis）

### 1. 上线前必做的配置改造

当前 `backend/config/settings.py` 是**开发默认配置**：包含硬编码的 Django 密钥、`DEBUG=True`、SQLite 数据库、进程内默认缓存以及仅限本机的 CORS 白名单。不能在未完成下表改造的情况下直接上线。

| 项目 | 生产要求 |
|---|---|
| 密钥与调试 | 从环境变量或密钥服务读取 `SECRET_KEY`；设置 `DEBUG=False`。不要提交 `.env`。 |
| 主机与跨域 | 设置真实 `ALLOWED_HOSTS`。若 Nginx 同域代理 `/api/`，通常不需要跨域；分域部署时仅白名单真实 HTTPS 前端域名。 |
| 数据库 | 将 `DATABASES` 切换到受管 PostgreSQL，并用环境变量保存连接信息。SQLite 不适合多进程 Web 服务与备份恢复。 |
| 缓存 | 将 Django `CACHES` 切换到共享 Redis。默认 `LocMemCache` 按进程隔离，无法保证多 Gunicorn worker 或定时抓取进程共享缓存与失效版本。 |
| 静态文件 | 配置 `STATIC_ROOT`，执行 `collectstatic`；前端产物由 Nginx 直接提供。 |
| 外网访问 | API 当前无鉴权。若不是受控内部工具，应在应用层增加认证；在此之前至少用 VPN、IP 白名单或反向代理访问控制限制入口。 |

建议在 `/etc/fundflow/fundflow.env` 以仅服务账户可读的权限保存运行配置，并让 Django 设置模块显式读取它；仅导出环境变量并不会自动改变当前代码中的硬编码设置。

共享缓存的最小配置如下。先在部署环境安装 Redis 服务和 Python `redis` 绑定，并将该依赖固定到生产依赖清单；随后在 `backend/config/settings.py` 中读取 `REDIS_URL` 并配置 Django 内置 Redis 缓存后端：

```bash
# 在虚拟环境中安装后，应同步更新项目的生产依赖锁定文件。
pip install redis
```

```python
# backend/config/settings.py
import os

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ["REDIS_URL"],
    }
}
```

`/etc/fundflow/fundflow.env` 至少应包含类似 `REDIS_URL=redis://:password@127.0.0.1:6379/1` 的连接串。Web 服务和 `fetch_sector_fund_flow` 定时任务必须加载同一份环境文件、连接同一个 Redis 实例，缓存版本更新才能跨进程生效。

### 2. 安装应用与迁移数据库

以下示例假定代码部署在 `/srv/fundflow`，服务账户为 `fundflow`。先完成上节的 Django 配置改造并准备 PostgreSQL、Redis，再执行：

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin fundflow
sudo mkdir -p /srv/fundflow /var/log/fundflow
sudo chown -R fundflow:fundflow /srv/fundflow /var/log/fundflow

# 使用 fundflow 用户获取本仓库代码后执行
cd /srv/fundflow/backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
# 将 Gunicorn 固定到项目的生产依赖后安装；它当前不在 requirements.txt 中。
pip install gunicorn
python manage.py migrate
python manage.py collectstatic --noinput

cd /srv/fundflow/frontend
npm ci
VITE_API_BASE=/api npm run build
```

首次部署在盘后可执行一次：

```bash
cd /srv/fundflow/backend
. .venv/bin/activate
python manage.py fetch_sector_fund_flow --latest
```

### 3. 启动 Django Web 服务

创建 `/etc/systemd/system/fundflow-web.service`：

```ini
[Unit]
Description=Fundflow Django API
After=network.target

[Service]
User=fundflow
Group=fundflow
WorkingDirectory=/srv/fundflow/backend
EnvironmentFile=/etc/fundflow/fundflow.env
ExecStart=/srv/fundflow/backend/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --access-logfile - --error-logfile -
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fundflow-web
sudo systemctl status fundflow-web
```

### 4. 定时抓取与日志

用 `cron` 或 systemd timer 均可。下面的 crontab 每 15 分钟触发一次，并用 `flock` 防止网络重试导致上一次尚未结束时发生并发抓取：

```cron
*/15 9-15 * * 1-5 flock -n /var/run/fundflow-fetch.lock /srv/fundflow/backend/.venv/bin/python /srv/fundflow/backend/manage.py fetch_sector_fund_flow >> /var/log/fundflow/fetch.log 2>&1
```

该任务在 09:00、午休、15:15 后、周末和法定节假日会由命令自身安全退出；不要把 `--latest` 放入常规定时任务。配置 `logrotate` 轮转 `/var/log/fundflow/fetch.log`，并告警以下现象：持续出现“多次重试后仍失败”、清洗时丢弃记录、连续交易刻度没有新快照、数据库/Redis 不可用或磁盘空间不足。

> 若系统的 `/var/run` 仅允许 root 写入，请改用由 `fundflow` 用户可写的锁文件路径，例如 `/srv/fundflow/run/fetch.lock`，并先创建目录。

### 5. Nginx、HTTPS 与同域 API

Nginx 应直接服务 `frontend/dist`，并把 `/api/` 反向代理给 Gunicorn。示例站点配置：

```nginx
server {
    listen 80;
    server_name fundflow.example.com;
    root /srv/fundflow/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

在真实环境中为该站点配置 TLS 证书，并将 HTTP 重定向到 HTTPS。部署新前端后重新执行 `VITE_API_BASE=/api npm run build`，确认 Nginx 可读取 `dist/`，然后执行 `nginx -t` 并平滑重载。

### 6. 发布、验证与回滚

发布顺序应为：备份数据库 → 拉取代码 → 安装锁定依赖 → 运行测试 → `migrate` → 构建前端 → 重启 Web 服务 → 检查 API 和定时任务。前端部署通常只需替换 `frontend/dist/`；数据库迁移必须在版本回滚前评估是否可逆。

```bash
cd /srv/fundflow/backend
. .venv/bin/activate
python manage.py test fundflow
python manage.py check
python manage.py makemigrations --check --dry-run

cd /srv/fundflow/frontend
npm run lint
npm run build

sudo systemctl restart fundflow-web
sudo journalctl -u fundflow-web -n 100 --no-pager
tail -n 100 /var/log/fundflow/fetch.log
```

重点验收：`/api/sectors/intraday/?inflow_top=25&outflow_top=25` 有数据时返回两个方向各至多 25 条；图表横轴显示 18 个交易刻度；首次进入只显示默认 10 条曲线；盘后或非交易日仍能读取最近有数据的日期；抓取失败时不会写入不完整分页结果。

## 开发验证

```bash
cd backend
python manage.py test fundflow
python manage.py check
python manage.py makemigrations --check --dry-run

cd ../frontend
npm run lint
npm run build
```
