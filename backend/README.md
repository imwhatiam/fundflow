# 板块资金流向监控 · 后端 (Django)

## 快速开始

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser  # 可选，方便用admin后台查看数据

# 首次运行需要先同步一次板块/成分股映射（低频任务）
# 行业板块默认从项目根目录(backend的上一级目录)下的"沪深京A股.csv"读取，
# 运行前请确认该文件已放在正确位置，否则命令会报错提示找不到文件
python manage.py sync_sectors --category industry

# 抓一次个股资金流快照(调试用，--force忽略交易时段检查)
python manage.py fetch_stock_fund_flow --force

python manage.py runserver 8000
```

打开 http://localhost:8000/api/sectors/intraday/?category=industry 应该能看到 JSON 数据。

## 两个 management command

| 命令 | 频率 | 作用 |
|---|---|---|
| `fetch_stock_fund_flow` | 每5分钟（交易时段内） | 抓全市场个股当日主力资金流快照，写入 `StockFundFlowSnapshot` |
| `sync_sectors` | 每天一次（建议收盘后） | 同步板块列表 + 成分股映射，写入 `Sector` / `SectorConstituent` |

板块级别的资金流曲线**不单独存储**，由 API 层实时用"板块→成分股"映射去个股快照表聚合算出（见 `fundflow/services/aggregation.py`）。

### sync_sectors 的数据来源

- `--category industry`（默认）：读取本地 CSV 文件 `沪深京A股.csv`（放在 backend 的**上一级目录**，即和 backend/、frontend/ 同级），按"所属行业"列分组生成板块映射，**不再请求东财接口**。
- `--category concept`：仍然请求东财板块列表+成分股接口（这份CSV导出里没有概念板块信息）。
- CSV文件路径可以用 `--csv-path /your/path.csv` 显式指定，不用的话默认按上面的相对位置找。
- 板块代码（`Sector.code`）对行业板块来说是根据行业名称算出的哈希值（如 `CSV1e39751b68`），不是东财的真实BK编码——因为CSV数据源里本来就没有这个编码，用哈希是为了保证同一个行业名称每次同步都稳定映射到同一条记录，不会重复插入。

## crontab 配置示例

```bash
crontab -e
```

```
# 交易日每5分钟抓一次个股资金流(命令内部会自动跳过非交易时段)
*/5 9-15 * * 1-5  cd /path/to/project && /path/to/venv/bin/python manage.py fetch_stock_fund_flow >> /var/log/fundflow/fetch.log 2>&1

# 每天收盘后同步一次板块成分股映射
30 15 * * 1-5  cd /path/to/project && /path/to/venv/bin/python manage.py sync_sectors >> /var/log/fundflow/sync_sectors.log 2>&1
```

## API

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/sectors/?category=industry` | 板块列表 |
| GET | `/api/sectors/intraday/?category=industry&date=2026-08-18&top=10` | 板块分时累计净流入曲线(聚合) |
| GET | `/api/stocks/<code>/intraday/?date=2026-08-18` | 单只个股分时累计净流入曲线 |

## 重要说明

- 东财接口是逆向出来的未公开接口，没有官方文档，字段编号可能随时变化。出问题时打开 https://data.eastmoney.com/zjlx/ 用浏览器开发者工具核对最新参数，更新 `fundflow/services/eastmoney_client.py` 里的 `FIELDS`/`DEFAULT_FS` 即可。
- 生产部署时记得把 `settings.py` 里的 `SECRET_KEY`、`DEBUG`、`ALLOWED_HOSTS`、`CORS_ALLOWED_ORIGINS` 换成真实值，数据库建议换成 Postgres（当前用的是开发用的 SQLite）。
- 这套接口仅供个人学习/工具使用，请勿高频请求或商用分发。
