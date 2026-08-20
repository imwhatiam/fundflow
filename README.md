# 行业板块资金流向监控系统

一个自建的 A 股**行业板块**主力资金流向监控工具：Django 后端定时抓取东方财富个股资金流数据，结合本地行业分类数据实时聚合成板块维度曲线，React + ECharts 前端负责可视化。参考原型是东方财富 App 里的"资金流向"页面（仅取其中"行业板块 · 当日走势"这一个场景）。

```
fundflow-monorepo/
├── backend/     Django 项目
├── frontend/    React + ECharts 前端
└── docs/        效果预览图等文档资源
```

---

## 目录

1. [功能设计](#1-功能设计)
2. [代码实现](#2-代码实现)
3. [部署运维](#3-部署运维)
4. [已知限制 / 后续规划](#4-已知限制--后续规划)

---

## 1. 功能设计

### 1.1 核心功能

| 功能 | 状态 | 说明 |
|---|---|---|
| 个股资金流定时抓取 | ✅ | 每15分钟全市场抓取一次，写入数据库 |
| 行业板块与成分股同步 | ✅ | 低频任务（建议每天一次），从本地CSV文件维护"板块→个股"映射 |
| 板块分时累计净流入曲线 | ✅ | 由个股数据实时聚合得出 |
| 个股分时累计净流入曲线 | ✅ | 提供了 API，前端暂未接入展示 |
| "当日走势"可视化 | ✅ | 多曲线图，末端标注板块名+数值，红涨绿跌配色 |

本系统只做**行业板块的当日分时曲线**这一个场景，明确不做的部分见 [4. 已知限制](#4-已知限制--后续规划)。

### 1.2 效果预览

真实联调截图（非效果图）：

![当日走势效果预览](docs/preview_intraday.png)

- 红色系＝主力净流入，颜色越深、线越粗代表流入越多
- 绿色系＝主力净流出
- 每条线末端直接标注板块名称和最新累计净额，还原原型截图里"曲线+行内图例"的风格

### 1.3 数据模型设计

系统里**不存储板块级别的时序数据**，只存个股级别的原始快照，板块曲线在查询时实时聚合。这样设计的原因：

- 板块成分股这层映射关系变化很慢（一般几个月才调整一次），没必要每15分钟跟着抓
- 个股快照是唯一的"事实来源"，板块数据可以随时按需重新聚合，不会有"抓取口径不一致导致个股/板块对不上"的问题
- 缺点是查询时有计算开销，所以聚合结果做了短 TTL 缓存（见 3.3.3）

```
Sector (行业板块)
 ├─ code (由行业名称哈希生成), name
 └─ constituents ──┐
                    ▼
        SectorConstituent (板块-个股映射，从本地CSV低频同步)
                    │  stock_code
                    ▼
        StockFundFlowSnapshot (个股快照，每15分钟一条，来自东财接口)
         ├─ stock_code, snapshot_time (唯一约束)
         ├─ main_net_inflow (主力净流入)
         └─ super_large / large / medium / small_net_inflow (超大单/大单/中单/小单)
```

---

## 2. 代码实现

### 2.1 技术栈

| 层 | 选型 |
|---|---|
| 后端框架 | Django 6 + Django REST Framework |
| 后端数据库 | SQLite（开发） / 建议生产换 PostgreSQL |
| 定时任务 | Linux crontab + Django management command（未引入 Celery，个人工具场景不需要那么重） |
| 前端框架 | React 19 + Vite |
| 图表库 | Apache ECharts |
| 前后端通信 | REST + axios，开发环境用 django-cors-headers 处理跨域 |

### 2.2 项目结构

```
backend/
├── manage.py
├── requirements.txt
├── config/                       Django 项目配置
│   ├── settings.py
│   └── urls.py                   挂载 /api/ -> fundflow.urls
└── fundflow/                     核心业务 app
    ├── models.py                 Sector / SectorConstituent / StockFundFlowSnapshot
    ├── serializers.py            DRF 序列化器
    ├── views.py                  3个API视图
    ├── urls.py
    ├── services/
    │   ├── eastmoney_client.py   东财接口调用封装（实时快照 + 个股分时历史）
    │   ├── csv_import.py         解析"沪深京A股.csv"，按所属行业分组（板块数据源）
    │   ├── aggregation.py        板块聚合核心逻辑
    │   └── backfill.py           可复用的历史数据回补工具（命令当前不自动调用）
    └── management/commands/
        ├── fetch_stock_fund_flow.py   交易时段抓快照；非交易时段直接退出
        └── sync_sectors.py            每天从CSV同步板块/成分股映射

frontend/
├── index.html
├── vite.config.js
└── src/
    ├── main.jsx
    ├── App.jsx                   页面主体：轮询、状态管理、渲染
    ├── index.css                 设计token与全局样式
    ├── api/client.js             axios封装，对应后端3个接口
    └── components/
        └── SectorFlowChart.jsx   ECharts多曲线图核心组件
```

### 2.3 后端实现细节

#### 2.3.1 数据抓取：`EastmoneyClient`

封装了对东财**未公开** JSON 接口的调用，保留两个方法：

- `fetch_all_stock_fund_flow()` — 分页获取全市场（沪深京）所有个股当日资金流字段（`push2.eastmoney.com/api/qt/clist/get`），而不是逐只股票请求。分页按股票代码稳定排序，并校验重复代码，避免限流或翻页漂移造成静默缺数。
- `fetch_stock_intraday_history(stock_code, market)` — 获取单只股票最近一个交易日的完整分时资金流曲线（`push2.eastmoney.com/api/qt/stock/fflow/kline/get`），供独立的历史回补工具复用，不由定时抓取命令自动调用。

字段编号（`f12`=代码、`f62`=主力净流入、`f51`-`f61`=分时数据点各字段等）是社区逆向出来的，**没有官方文档**，接口随时可能变。出问题时打开 `https://data.eastmoney.com/zjlx/`，浏览器开发者工具 Network 面板抓包核对最新参数，改 `eastmoney_client.py` 顶部的常量即可，不需要动其它代码。个股分时历史接口的字段顺序尤其不确定（是参照板块历史资金流接口的公开资料推断的），如果解析出来的数值不对劲，同样需要抓包核实。

请求内置了重试（默认2次，指数退避）和字段清洗（`-`/空值统一转 `None`，过滤掉停牌等无效行）。

> 板块列表/成分股接口原来也是走东财的，现在行业板块数据改从本地CSV导入，这部分代码已经删掉了，不是保留着没用。

#### 2.3.2 定时抓取命令

**`fetch_stock_fund_flow`**——命令只在交易时段抓取数据，其他时段立即退出：

| 运行时刻 | 行为 |
|---|---|
| 交易时段内（9:30-11:30 / 13:00-15:00） | 批量抓全市场"当前这一个时间点"的快照，按15分钟对齐写入 |
| 非交易时段（午休、早盘前、收盘后、周末） | 直接退出，不发起网络请求，也不写入数据库 |

一些实现细节：
- 把执行时间向下取整到最近的15分钟刻度再落库，避免 cron 实际触发延迟导致同一个"15分钟窗口"被记成两条数据
- 用 `bulk_create(ignore_conflicts=True)` 批量写入，配合 `(stock_code, snapshot_time)` 唯一约束，命令可以安全地被重复执行（幂等）

`--force` 仅用于调试，可跳过交易时段检查；正常 cron 任务不要添加该参数。API 未指定 `date` 时，会查询数据库中最近一个有快照的交易日；历史日期固定返回 09:30-15:00 的 18 个标准15分钟刻度。

**`sync_sectors`**（每天一次）：
- 从本地 CSV 文件（`沪深京A股.csv`，需放在项目根目录，即与 `backend/`、`frontend/` 同级）读取，按"所属行业"列分组。文件是 UTF-16 编码、制表符分隔的典型行情软件导出格式；解析逻辑见 `fundflow/services/csv_import.py`
- CSV里"所属行业"为 `--`/空 等占位符的行（常见于北交所新股、定向转让品种等暂无行业分类的股票）会被过滤掉，不会生成一个假板块
- 因为CSV数据源没有像东财 BK0490 那样的官方板块代码，`Sector.code` 用行业名称的哈希值生成（如 `CSV1e39751b68`），保证同一行业名每次同步都稳定映射到同一条记录，重复导入不会产生重复板块
- 遵循"先清空该板块旧成分股、再整体写入最新的"的更新策略；同步结束后还会**清理这次没出现过的旧板块**（比如CSV数据源的行业分类调整了），避免野板块一直残留

#### 2.3.3 板块聚合：`services/aggregation.py`

核心函数 `aggregate_sector_intraday(trade_date, inflow_top, outflow_top)`：

1. 根据交易日和当前时间生成已经到达的标准15分钟刻度，作为所有板块曲线对齐的公共X轴；历史遗留的5分钟数据不会混入
2. 对每个板块，用它的成分股代码去查 `StockFundFlowSnapshot`，按 `snapshot_time` 分组 `Sum(main_net_inflow)`
3. 把每个板块的聚合结果对齐到公共X轴上——某个时间点该板块暂时没数据时，**用上一个已知值前向填充**，而不是填0（填0会在图上制造出不存在的"资金骤降到0"假象）
4. 分别按最新净流入排序，独立选取 `inflow_top` 个流入板块和 `outflow_top` 个流出板块；默认各取5个
5. 结果做45秒 TTL 缓存；时间进入下一个15分钟窗口或抓取命令写入新快照时会切换缓存版本

#### 2.3.4 REST API

| Method | Path | 参数 | 说明 |
|---|---|---|---|
| GET | `/api/sectors/` | 无 | 行业板块列表 |
| GET | `/api/sectors/intraday/` | `date`, `inflow_top`, `outflow_top` | 板块分时聚合曲线，默认流入/流出各5个 |
| GET | `/api/stocks/<code>/intraday/` | `date` | 单只个股分时曲线 |

MVP阶段没做鉴权（`DEFAULT_PERMISSION_CLASSES = []`），按个人/小团队工具场景设计；对外提供服务前需要补上。

### 2.4 前端实现细节

#### 2.4.1 数据流

```
App.jsx (轮询, 30秒/次)
  └─ fetchSectorIntraday(inflowTop, outflowTop) [api/client.js]
       └─ GET /api/sectors/intraday/
            └─ setData() → 传给 SectorFlowChart 渲染
```

页面只有一个视图（板块当日走势），没有 tab 切换，也没有板块类别选择——整个前端就是加载态 / 错误态 / 图表三种状态的直接呈现。`App.jsx` 在 `series` 为空时会提示"今天还没数据，检查定时任务是否跑过"，而不是空白页。

#### 2.4.2 图表组件：`SectorFlowChart.jsx`

用 ECharts 的 `line` 系列 + `endLabel` 实现"曲线末端直接标名字+数值"的效果，核心逻辑：

- `buildSeriesStyle()`：把 series 按 `latest_net_inflow` 正负分组，分别按幅度大小分配红/绿三档深浅色；每组绝对值最大的前两个加粗
- `labelLayout: { moveOverlap: 'shiftY' }`：多条线末端标签重叠时自动错开
- X轴使用分钟数值轴，范围固定为 `09:30–15:00`，每15分钟显示一个刻度，即使当前数据尚未覆盖全天也不会自动收缩
- tooltip 用 `trigger: 'axis'`，hover 时按数值从高到低排序显示所有板块当前值

#### 2.4.3 设计取舍

- 颜色/字体走"数据终端"风格：白底、克制的灰色网格线、红涨绿跌，数值用等宽字体（`--font-data`）保证对齐
- 没引入 Redux/Zustand 等状态库——当前只有一个数据源、一层轮询，`useState`+`useEffect` 足够，过度设计没有必要
- echarts 全量引入导致构建产物约1.3MB（gzip后约450KB），量级下如果关心首屏体积可以按需引入 `echarts/core` + 具体图表/组件，本期没做这个优化

---

## 3. 部署运维

### 3.1 环境要求

- Python 3.10+，Node.js 18+
- Linux 服务器（用于配置 crontab；Windows 也能跑但定时任务需要换成计划任务）
- 生产环境建议：PostgreSQL、Redis（缓存）、Nginx（反代+静态托管）

### 3.2 本地开发环境搭建

```bash
# 先把"沪深京A股.csv"放到项目根目录（与 backend/、frontend/ 同级）

# 后端
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py sync_sectors                    # 首次需要，从CSV同步板块映射
python manage.py fetch_stock_fund_flow --force    # 抓一次数据，方便前端有内容可看
python manage.py runserver 8000

# 前端（新开一个终端）
cd frontend
npm install
npm run dev       # 默认 http://localhost:5173，请求 http://localhost:8000/api
```

### 3.3 生产部署

#### 3.3.1 后端

```bash
cd backend
pip install -r requirements.txt gunicorn psycopg2-binary

# settings.py 需要修改的地方：
#   SECRET_KEY   -> 换成真实密钥，不要用仓库里的开发密钥
#   DEBUG        -> False
#   ALLOWED_HOSTS -> 填真实域名
#   DATABASES    -> 换成 PostgreSQL
#   CORS_ALLOWED_ORIGINS -> 填前端真实域名
#   CACHES       -> 换成 Redis（默认本地内存缓存不支持多进程/多机共享）

python manage.py migrate
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

#### 3.3.2 前端

```bash
cd frontend
VITE_API_BASE=https://your-domain.com/api npm run build
# 产物在 dist/，纯静态文件，交给 Nginx 托管
```

#### 3.3.3 Nginx 参考配置

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        root /path/to/frontend/dist;
        try_files $uri /index.html;
    }
}
```

### 3.4 定时任务（crontab）

```bash
crontab -e
```

```cron
# 工作日 9:00-15:59 每15分钟运行；命令会在非交易时段直接退出
*/15 9-15 * * 1-5  cd /path/to/backend && /path/to/venv/bin/python manage.py fetch_stock_fund_flow >> /var/log/fundflow/fetch.log 2>&1

# 每天收盘后同步一次板块成分股映射（需要"沪深京A股.csv"已经是当天/最新的文件）
30 15 * * 1-5  cd /path/to/backend && /path/to/venv/bin/python manage.py sync_sectors >> /var/log/fundflow/sync_sectors.log 2>&1
```

建议提前 `mkdir -p /var/log/fundflow` 并给运行用户写权限，避免第一次跑 cron 时因为目录不存在而静默失败。如果 CSV 文件是定期手动更新/从别处同步过来的，确保它在 `sync_sectors` 执行前已经就位。

**非交易时段运行行为**：命令只输出退出提示，不创建东财客户端、不发网络请求、不写数据库。网页 API 默认读取数据库中最近一个有数据的交易日，因此收盘后或周末仍可展示最近交易日曲线。

### 3.5 日志与监控

- 两个命令都用标准 `logging` 输出（东财请求失败、重试、抓取条数、CSV解析统计等都有日志），生产环境可以接 ELK/Loki 之类的日志系统，或者简单地 `grep ERROR /var/log/fundflow/*.log` 做个每日巡检脚本
- 建议监控点：`fetch_stock_fund_flow` 单次执行耗时（正常应在几秒到十几秒，如果明显变长可能是东财接口变慢或本机网络问题）、连续失败次数（连续失败可能是接口字段变了，需要人工核对更新）、`sync_sectors` 每次同步的板块数/成分股数是否有异常波动（可能意味着CSV文件损坏或格式变了）

### 3.6 常见故障排查

| 现象 | 可能原因 | 排查方式 |
|---|---|---|
| 前端一直显示"加载失败" | 后端没启动 / CORS配置不对 | 先直接 `curl http://后端地址/api/sectors/intraday/` 看后端本身是否正常 |
| 前端显示"今天还没有数据" | crontab 没配置/没跑起来，或今天还没到抓取时间点 | `python manage.py fetch_stock_fund_flow --force --dry-run` 手动测一下抓取是否正常 |
| 板块曲线是空的，但个股接口有数据 | 没跑过 `sync_sectors`，板块-成分股映射表是空的 | `python manage.py sync_sectors` |
| `sync_sectors` 报"找不到CSV文件" | `沪深京A股.csv` 没放在项目根目录，或文件名/路径不对 | 确认文件与 `backend/`、`frontend/` 同级，或用 `--csv-path` 显式指定路径 |
| `sync_sectors` 报"CSV文件缺少必需列" | CSV导出格式变了，或用错了文件 | 用文本编辑器/Excel打开确认表头含"代码""名称""所属行业"三列 |
| 抓取脚本报错/返回0条 | 东财接口字段或参数变了 | 浏览器开发者工具抓包 `data.eastmoney.com/zjlx/` 对照更新 `eastmoney_client.py` |
| 非交易时段仍发起东财请求 | cron 命令可能带了 `--force` | 移除 `--force`；该参数只用于手动调试 |

### 3.7 合规与限流提示

东财个股资金流接口是**未公开的逆向接口**，没有官方授权：

- 仅建议个人学习/工具使用，不要做成高并发对外商用服务
- 已内置的节流措施：个股快照接口每15分钟一次批量请求（不是循环请求每只股票）
- 如果要合规商用，需评估采购东财 Choice 数据授权，或改用有官方授权的行情数据商
- 行业分类数据来自本地CSV文件（用户自行提供/更新），不涉及对东财板块接口的请求

---

## 4. 已知限制 / 后续规划

明确不做的（按需求范围裁掉，不是技术上做不了）：

- 概念板块——已整体移除，系统只做行业板块
- 大盘指数分时涨跌幅副图——原型截图底部的上证指数曲线，本系统不做
- "多日累计""主力净额""相对流入""涨跌幅"等其它视图——本系统只做"当日走势"这一个场景，前端也没有 tab 切换机制

技术债 / 可以后续优化的：

- [ ] 板块聚合目前是同步计算，板块数量大或成分股很多时可能有性能瓶颈，可以考虑改成定时任务预计算+写缓存，而不是请求时现算
- [ ] 未做鉴权，仅适合内网/个人使用场景
- [ ] 历史某天的数据回看：只要 `StockFundFlowSnapshot` 里有对应日期的数据就能查（API已支持`date`参数），但数据库会随时间增长，需要考虑归档/清理策略
- [ ] `沪深京A股.csv` 目前需要手动放置/更新，没有自动化的文件同步机制
- [ ] 当前未接入法定节假日交易日历；工作日遇休市日时，命令仍会按时间窗口尝试抓取，接口返回空数据后中止写入
- [ ] 定时命令不自动回补缺失的历史时间点；cron 中断期间的数据需要通过独立回补流程处理
