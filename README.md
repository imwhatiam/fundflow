# 板块资金流向监控系统

一个自建的 A 股板块（行业/概念）主力资金流向监控工具：Django 后端定时抓取东方财富个股资金流数据，实时聚合成板块维度曲线，React + ECharts 前端负责可视化。参考原型是东方财富 App 里的"资金流向"页面。

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
| 个股资金流定时抓取 | ✅ | 每5分钟全市场抓取一次，写入数据库 |
| 板块列表与成分股同步 | ✅ | 低频任务（建议每天一次），维护"板块→个股"映射 |
| 板块分时累计净流入曲线 | ✅ | 由个股数据实时聚合得出，行业/概念板块可切换 |
| 个股分时累计净流入曲线 | ✅ | 提供了 API，前端暂未接入展示 |
| "当日走势"可视化 | ✅ | 多曲线图，末端标注板块名+数值，红涨绿跌配色 |
| 大盘指数分时涨跌幅副图 | ❌ 未实现 | 原型截图底部的上证指数曲线，本期未做 |
| "多日累计""主力净额"等其它4个 tab | ❌ 未实现 | 前端仅做了 tab 占位，未接后端数据 |

### 1.2 效果预览

当前"当日走势"tab 的真实渲染效果（本地联调截图，非效果图）：

![当日走势效果预览](docs/preview_intraday.png)

- 红色系＝主力净流入，颜色越深、线越粗代表流入越多（图中"芯片"）
- 绿色系＝主力净流出（图中"AI应用"" 数字经济"）
- 每条线末端直接标注板块名称和最新累计净额，还原原型截图里"曲线+行内图例"的风格

### 1.3 与原型的对应关系

| 原型截图元素 | 本系统实现 |
|---|---|
| 顶部 5 个 tab（主力净额/相对流入/涨跌幅/当日走势/多日累计） | 只实现了"当日走势"，其余为占位 |
| 多曲线板块资金流图 | ✅ 完整实现，数据来自个股聚合 |
| 右侧板块名称+数值标注 | ✅ 用 ECharts `endLabel` 实现，效果高度还原 |
| 底部大盘指数涨跌幅副图 | ❌ 未实现 |
| 图表设置（切换行业/概念/地域板块） | ✅ 行业/概念可切换，地域板块未做 |

### 1.4 数据模型设计

系统里**不存储板块级别的时序数据**，只存个股级别的原始快照，板块曲线在查询时实时聚合。这样设计的原因：

- 板块成分股这层映射关系变化很慢（一般几个月才调整一次），没必要每5分钟跟着抓
- 个股快照是唯一的"事实来源"，板块数据可以随时按需重新聚合，不会有"抓取口径不一致导致个股/板块对不上"的问题
- 缺点是查询时有计算开销，所以聚合结果做了短 TTL 缓存（见 3.3.3）

```
Sector (板块)
 ├─ code, name, category(行业/概念)
 └─ constituents ──┐
                    ▼
        SectorConstituent (板块-个股映射，低频同步)
                    │  stock_code
                    ▼
        StockFundFlowSnapshot (个股快照，每5分钟一条)
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
    │   ├── eastmoney_client.py   东财接口调用封装（个股快照 + 概念板块列表/成分股）
    │   ├── csv_import.py         解析"沪深京A股.csv"，按所属行业分组（行业板块数据源）
    │   └── aggregation.py        板块聚合核心逻辑
    └── management/commands/
        ├── fetch_stock_fund_flow.py   每5分钟抓个股快照
        └── sync_sectors.py            每天同步板块/成分股映射

frontend/
├── index.html
├── vite.config.js
└── src/
    ├── main.jsx
    ├── App.jsx                   页面主体：tab切换、轮询、状态管理
    ├── index.css                 设计token与全局样式
    ├── api/client.js             axios封装，对应后端3个接口
    └── components/
        ├── TabBar.jsx            顶部tab栏+行业/概念切换
        └── SectorFlowChart.jsx   ECharts多曲线图核心组件
```

### 2.3 后端实现细节

#### 2.3.1 数据抓取：`EastmoneyClient`

封装了对东财**未公开** JSON 接口（`push2.eastmoney.com/api/qt/clist/get`）的调用，提供三个方法：

- `fetch_all_stock_fund_flow()` — 一次请求拿全市场（沪深京）所有个股当日资金流字段，而不是逐只股票请求。全市场约5000+只股票，一次分页足够，避免了5000次请求带来的耗时和被限流风险。
- `fetch_sector_list(category)` — 拿行业板块（`fs=m:90+t:2`）或概念板块（`fs=m:90+t:3`）的代码+名称列表
- `fetch_sector_constituents(sector_code)` — 拿某个板块的成分股列表（`fs=b:{板块代码}`）

字段编号（`f12`=代码、`f62`=主力净流入等）是社区逆向出来的，**没有官方文档**，接口随时可能变。出问题时打开 `https://data.eastmoney.com/zjlx/`，浏览器开发者工具 Network 面板抓包核对最新参数，改 `eastmoney_client.py` 顶部的常量即可，不需要动其它代码。

请求内置了重试（默认2次，指数退避）和字段清洗（`-`/空值统一转 `None`，过滤掉停牌等无效行）。

#### 2.3.2 定时抓取命令

**`fetch_stock_fund_flow`**（每5分钟）：
- 命令内部自己判断是否在 A 股交易时段（9:30-11:30 / 13:00-15:00 且工作日），非交易时段自动跳过——这样 crontab 只需要写粗粒度的 `*/5 9-15 * * 1-5`，不用精确卡时间窗口
- 把执行时间向下取整到最近的5分钟刻度再落库，避免 cron 实际触发延迟几秒导致同一个"5分钟窗口"被记成两条数据
- 用 `bulk_create(ignore_conflicts=True)` 批量写入，配合 `(stock_code, snapshot_time)` 唯一约束，命令可以安全地被重复执行（幂等）

**`sync_sectors`**（每天一次）：
- **行业板块**：从本地 CSV 文件（`沪深京A股.csv`，需放在项目根目录，即与 `backend/`、`frontend/` 同级）读取，按"所属行业"列分组。文件由 UTF-16 编码、制表符分隔，是典型的行情软件导出格式；解析逻辑见 `fundflow/services/csv_import.py`。因为CSV数据源没有像东财 BK0490 那样的官方板块代码，`Sector.code` 用行业名称的哈希值生成（如 `CSV1e39751b68`），保证同一行业名每次同步都稳定映射到同一条记录，重复导入不会产生重复板块。
- **概念板块**：仍走东财接口（CSV导出里没有概念板块信息），逻辑不变——先拿板块列表，再逐个板块请求成分股（节流间隔默认0.3秒/个）。
- 两种来源都遵循"先清空该板块旧成分股、再整体写入最新的"的更新策略，避免"调出板块的股票"残留。

#### 2.3.3 板块聚合：`services/aggregation.py`

核心函数 `aggregate_sector_intraday(category, trade_date, top)`：

1. 先查出当天所有个股快照的时间点集合，作为所有板块曲线对齐的公共X轴
2. 对每个板块，用它的成分股代码去查 `StockFundFlowSnapshot`，按 `snapshot_time` 分组 `Sum(main_net_inflow)`
3. 把每个板块的聚合结果对齐到公共X轴上——某个时间点该板块暂时没数据时，**用上一个已知值前向填充**，而不是填0（填0会在图上制造出不存在的"资金骤降到0"假象）
4. 按最新净流入的**绝对值**排序取 top N（这样正向流入最多和负向流出最多的板块都能露出来，而不是清一色只显示流入最多的）
5. 结果做45秒 TTL 缓存（`django.core.cache`，开发环境是本地内存缓存，生产建议换 Redis）

#### 2.3.4 REST API

| Method | Path | 参数 | 说明 |
|---|---|---|---|
| GET | `/api/sectors/` | `category` | 板块列表 |
| GET | `/api/sectors/intraday/` | `category`, `date`, `top` | 板块分时聚合曲线 |
| GET | `/api/stocks/<code>/intraday/` | `date` | 单只个股分时曲线 |

MVP阶段没做鉴权（`DEFAULT_PERMISSION_CLASSES = []`），按个人/小团队工具场景设计；对外提供服务前需要补上。

### 2.4 前端实现细节

#### 2.4.1 数据流

```
App.jsx (轮询, 30秒/次)
  └─ fetchSectorIntraday(category, top) [api/client.js]
       └─ GET /api/sectors/intraday/
            └─ setData() → 传给 SectorFlowChart 渲染
```

`App.jsx` 管理三种状态：`loading` / `error` / `ready`，并在 `ready` 且 `series` 为空时给出"今天还没数据，检查定时任务是否跑过"的提示，而不是空白页。

#### 2.4.2 图表组件：`SectorFlowChart.jsx`

用 ECharts 的 `line` 系列 + `endLabel` 实现"曲线末端直接标名字+数值"的效果，核心逻辑：

- `buildSeriesStyle()`：把 series 按 `latest_net_inflow` 正负分组，分别按幅度大小分配红/绿三档深浅色；每组绝对值最大的前两个加粗（对应原型截图里"芯片/通信"字体更大更粗、中间几条细灰线）
- `labelLayout: { moveOverlap: 'shiftY' }`：多条线末端标签重叠时自动错开
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
# 后端
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py sync_sectors --category industry     # 首次需要，同步板块映射
python manage.py fetch_stock_fund_flow --force         # 抓一次数据，方便前端有内容可看
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
# 交易日 9:00-15:10 每5分钟抓一次个股资金流（命令内部会自动跳过非交易时段，粗粒度cron即可）
*/5 9-15 * * 1-5  cd /path/to/backend && /path/to/venv/bin/python manage.py fetch_stock_fund_flow >> /var/log/fundflow/fetch.log 2>&1

# 每天收盘后同步一次板块成分股映射
30 15 * * 1-5  cd /path/to/backend && /path/to/venv/bin/python manage.py sync_sectors >> /var/log/fundflow/sync_sectors.log 2>&1
```

建议提前 `mkdir -p /var/log/fundflow` 并给运行用户写权限，避免第一次跑 cron 时因为目录不存在而静默失败。

### 3.5 日志与监控

- 两个命令都用标准 `logging` 输出（东财请求失败、重试、抓取条数等都有日志），生产环境可以接 ELK/Loki 之类的日志系统，或者简单地 `grep ERROR /var/log/fundflow/*.log` 做个每日巡检脚本
- 建议监控点：`fetch_stock_fund_flow` 单次执行耗时（正常应在几秒到十几秒，如果明显变长可能是东财接口变慢或本机网络问题）、连续失败次数（连续失败可能是接口字段变了，需要人工核对更新）

### 3.6 常见故障排查

| 现象 | 可能原因 | 排查方式 |
|---|---|---|
| 前端一直显示"加载失败" | 后端没启动 / CORS配置不对 | 先直接 `curl http://后端地址/api/sectors/intraday/` 看后端本身是否正常 |
| 前端显示"今天还没有数据" | crontab 没配置/没跑起来，或今天还没到抓取时间点 | `python manage.py fetch_stock_fund_flow --force --dry-run` 手动测一下抓取是否正常 |
| 板块曲线是空的，但个股接口有数据 | 没跑过 `sync_sectors`，板块-成分股映射表是空的 | `python manage.py sync_sectors --category industry` |
| `sync_sectors --category industry` 报"找不到CSV文件" | `沪深京A股.csv` 没放在项目根目录，或文件名/路径不对 | 确认文件与 `backend/`、`frontend/` 同级，或用 `--csv-path` 显式指定路径 |
| `sync_sectors` 报"CSV文件缺少必需列" | CSV导出格式变了，或用错了文件 | 用文本编辑器/Excel打开确认表头含"代码""名称""所属行业"三列 |
| 抓取脚本报错/返回0条 | 东财接口字段或参数变了 | 浏览器开发者工具抓包 `data.eastmoney.com/zjlx/` 对照更新 `eastmoney_client.py` |

### 3.7 合规与限流提示

东财资金流接口是**未公开的逆向接口**，没有官方授权：

- 仅建议个人学习/工具使用，不要做成高并发对外商用服务
- 已内置的节流措施：个股快照接口每5分钟一次批量请求（不是循环请求每只股票）；`sync_sectors` 请求成分股时有 0.3 秒/个的间隔
- 如果要合规商用，需评估采购东财 Choice 数据授权，或改用有官方授权的行情数据商

---

## 4. 已知限制 / 后续规划

- [ ] 大盘指数分时涨跌幅副图未实现
- [ ] "多日累计""主力净额""相对流入""涨跌幅"4个tab还是前端占位，未接数据
- [ ] 地域板块（原型"图表设置"里应该还有这个维度）未实现
- [ ] 板块聚合目前是同步计算，板块数量大或成分股很多时可能有性能瓶颈，可以考虑改成定时任务预计算+写缓存，而不是请求时现算
- [ ] 未做鉴权，仅适合内网/个人使用场景
- [ ] 历史某天的数据回看：只要 `StockFundFlowSnapshot` 里有对应日期的数据就能查（API已支持`date`参数），但数据库会随时间增长，需要考虑归档/清理策略
