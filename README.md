# 三级行业资金流向监控

这是一个 Django + React 单仓库应用，用于定时抓取东方财富三级行业资金流，按 15 分钟交易刻度保存快照，并展示当日资金净流入、净流出走势。

## 当前功能

- 数据源：东方财富三级行业列表接口 `push2.eastmoney.com/api/qt/clist/get`。
- 行业范围：仅抓取三级行业，筛选为 `fs=m:90+s:8+f:!50`；不保留二级行业或混合板块数据。
- 每轮抓取固定发送两次请求：
  - `fid=f62&po=1&pn=1&pz=50`：主力净流入 Top 50。
  - `fid=f62&po=0&pn=1&pz=50`：主力净流出 Top 50。
- 两次结果按板块代码合并；重复板块使用后发出的流出榜响应数据。
- 在首个榜单请求成功后，发起另一个榜单请求前固定等待 120 秒。每个榜单的初始请求失败后最多重试 5 次；重试间隔在首个请求前随机生成、彼此不同且每次不少于 45 秒。10 个重试间隔与 1 个成功间隔的计划总和不超过 700 秒，并以严格小于 890 秒的单轮抓取硬截止。
- 单个方向失败时保留另一方向的数据并记录该刻度的双榜状态；两个方向都失败时不写数据库。
- 前端一次获取流入、流出各 25 条，图表默认显示两侧各 5 条，可通过复选框增删曲线。
- 前端不使用浏览器缓存，也不自动轮询；重复 API 查询由服务端缓存处理。

## 项目结构

```text
backend/
├── config/                         # Django 配置与路由
└── fundflow/
    ├── management/commands/
    │   └── fetch_sector_fund_flow.py
    ├── migrations/                 # 数据库迁移
    ├── services/
    │   ├── eastmoney/              # 间隔计划、HTTP、解析和双榜请求编排
    │   ├── snapshot_time.py        # 交易时段和快照时间对齐
    │   ├── snapshot_collection.py  # 抓取结果与快照时间组合
    │   ├── snapshot_writer.py      # 原子化写库和提交后缓存失效
    │   ├── sector_intraday_queries.py   # 只读 ORM 查询
    │   ├── sector_intraday_builders.py  # 纯数据聚合与 stale 判断
    │   ├── sector_intraday_service.py   # 缓存和分时查询协调
    │   ├── trading_calendar.py     # 交易日判断
    │   └── trading_time.py         # 15 分钟交易刻度
    ├── models.py                   # 三级行业资金流快照模型
    ├── views.py                    # 薄 DRF API 层
    └── urls.py
frontend/src/
├── api/client.js                   # Axios 客户端
├── components/                     # 图表和排行列表
├── features/sector-flow/           # 页面、数据请求/勾选 hooks、纯曲线 helpers
├── App.jsx                         # 薄应用入口
└── index.css
docs/                               # 文档图片
```

## 数据与时间规则

`EastmoneySectorFundFlowSnapshot` 只保存三级行业的板块代码、名称、指数涨跌、主力及各档资金净流入；`(sector_code, snapshot_time)` 是唯一约束。同一刻度重新抓取时会更新已存在的板块记录。`EastmoneySectorFundFlowSnapshotStatus` 单独记录流入榜、流出榜是否成功，避免部分响应被误判为完整快照。

交易时段为：

- 上午 `09:30–11:30`
- 下午 `13:00–15:00`

每天共 18 个 15 分钟刻度。命令启动时间向下对齐，例如：

- 09:35 → 09:30
- 10:10 → 10:00
- 11:15 → 11:15

交易日使用 `chinese-calendar` 判断，并额外排除周六、周日。交易所临时休市等法定节假日之外的例外需单独维护。

聚合只允许当前刻度实际榜单中的板块参与 Top N。已入选板块缺失中间刻度时使用前一个已知值填充；首次出现前没有历史快照的刻度显示为 0。若当前刻度的流入榜或流出榜请求失败（或没有该方向记录），该方向严格使用上一个 15 分钟刻度的数据，并标记为陈旧。

## 管理命令

在 `backend/` 中运行：

```bash
python manage.py fetch_sector_fund_flow
```

仅在交易时段发请求。非交易时段、周末和法定节假日直接退出，不访问东方财富，也不写数据库。

```bash
python manage.py fetch_sector_fund_flow --latest
```

用于非交易时段初始化或恢复数据。命令优先采用东财 `f124` 行情时间，并对齐到最近合法交易刻度。交易时段内传入 `--latest` 时仍按正常实时抓取处理。

```bash
python manage.py fetch_sector_fund_flow --dry-run
```

执行真实请求并打印前几条清洗结果，但不写数据库。参数可以组合，例如 `--latest --dry-run`。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/sectors/` | 返回指定日期最近快照中的三级行业列表。 |
| `GET` | `/api/sectors/intraday/` | 返回三级行业分时累计主力净流入曲线。 |

分时接口参数：

```text
/api/sectors/intraday/?date=2026-08-27&inflow_top=25&outflow_top=25
```

- `date`：可选，格式为 `YYYY-MM-DD`；省略时使用数据库中最近有数据的日期。
- `inflow_top`、`outflow_top`：可选，默认各 5，允许 0，单侧最大 30。
- `stale`：表示标准时间轴缺少快照、当前双榜有任一方向不完整，或任一方向已回退到上一个刻度。

## 服务端缓存

开发环境使用 Django `FileBasedCache`，目录为 `backend/.cache/django/`。Web 服务和管理命令可在同一台机器上共享缓存版本；成功写入快照后会更新对应交易日的版本键。

当前交易日的聚合结果缓存到下一个交易刻度，历史日期缓存两天。生产环境必须改用 Redis 等跨进程、跨主机共享缓存，不应使用本地文件缓存。

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
npm install
npm run dev
```

前端默认请求 `http://localhost:8000/api`。需要修改后端地址时创建 `frontend/.env.local`：

```dotenv
VITE_API_BASE=http://127.0.0.1:8000/api
```

## 测试与构建

```bash
cd backend
python manage.py test fundflow
python manage.py check
python manage.py makemigrations --check --dry-run

cd ../frontend
npm run lint
npm run build
```

前端尚未配置自动化测试，发布前还应人工检查加载、空数据、错误、陈旧数据、复选框和移动端布局。

## 生产部署

当前 `backend/config/settings.py` 是开发配置：使用硬编码密钥、`DEBUG=True`、SQLite、本地文件缓存和本机 CORS 白名单。上线前必须完成以下调整：

1. 从环境变量或密钥服务读取 `SECRET_KEY`，设置 `DEBUG=False`。
2. 配置真实 `ALLOWED_HOSTS`；前后端分域时仅允许实际 HTTPS 前端域名。
3. 将数据库切换为 PostgreSQL。
4. 将缓存切换为 Redis，确保 Web worker 与定时任务使用同一个实例。
5. 安装并固定生产依赖，例如 Gunicorn、PostgreSQL 驱动和 `redis`；它们当前不在 `backend/requirements.txt` 中。
6. 使用独立服务账户运行应用，限制环境文件、日志和数据库凭据权限。

推荐部署目录：

```text
/srv/fundflow/
├── backend/
├── frontend/dist/
└── .venv/
```

后端可由 systemd 管理 Gunicorn，Nginx 托管 `frontend/dist/` 并将 `/api/` 反向代理到 Gunicorn。生产环境应启用 HTTPS、访问日志、错误日志和日志轮转。

### 定时抓取

```cron
*/15 9-15 * * 1-5 flock -n /var/run/fundflow-fetch.lock /srv/fundflow/.venv/bin/python /srv/fundflow/backend/manage.py fetch_sector_fund_flow >> /var/log/fundflow/fetch.log 2>&1
```

`flock` 防止上一轮因 120 秒跨榜单等待、重试或网络超时尚未结束时启动重叠任务。命令会自行过滤开盘前、午休、收盘后、周末和法定节假日。

部署完成后可在非交易时段初始化：

```bash
cd /srv/fundflow/backend
/srv/fundflow/.venv/bin/python manage.py migrate
/srv/fundflow/.venv/bin/python manage.py fetch_sector_fund_flow --latest
```

### 发布检查

- 后端检查、迁移检查、单元测试、前端 lint 和 build 全部通过。
- `/api/sectors/intraday/?inflow_top=25&outflow_top=25` 能返回预期数据。
- 非交易时段不带 `--latest` 的抓取命令不发送请求。
- Web 服务和定时任务连接同一数据库及 Redis。
- 日志中没有持续的 `ProxyError`、超时、JSON 解析错误或两个排行榜同时失败。
- 准备数据库备份、静态文件回滚包和上一版本应用代码。

## 已知限制

东方财富接口不是正式开放 API，字段、主机可用性和访问策略可能随时变化。系统只保存每轮两个三级行业 Top 50 排行榜的并集，不保存完整行业全集快照；某板块进入排行榜前的历史曲线可能缺少真实值。请控制请求频率，不要将伪造 IP 或绕过访问限制作为稳定性方案。
