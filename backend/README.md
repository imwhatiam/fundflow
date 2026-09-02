# 后端运行说明

后端只维护东方财富三级行业资金流快照。每轮只抓取流入 Top 50 与流出 Top 50 两个榜单：首个请求成功后固定等待 120 秒再请求另一个榜单。每个榜单初始请求失败后最多重试 5 次；重试间隔在首请求前随机生成、每次彼此不同且至少 45 秒，全部计划间隔总和不超过 700 秒，单轮抓取严格限制在 890 秒以内。

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py fetch_sector_fund_flow
python manage.py runserver 8000
```

`fetch_sector_fund_flow` 仅在 A 股交易时段抓取并写入 15 分钟刻度。交易日判断使用 `chinese-calendar` 过滤法定节假日，调休周末仍按休市处理。同一刻度重跑会更新已抓到的板块记录。

每个快照会记录流入榜、流出榜是否成功。单方向失败时仍保存另一侧数据；分时 API 会将该方向回退到上一个 15 分钟刻度，并在响应中返回 `stale: true`。两个方向都失败时不写数据库。

在非交易时段，正常命令直接退出；需要初始化或恢复一份最近可用快照时执行：

```bash
python manage.py fetch_sector_fund_flow --latest
```

生产定时任务示例：

```cron
*/15 9-15 * * 1-5 flock -n /var/run/fundflow-fetch.lock /path/to/venv/bin/python /path/to/backend/manage.py fetch_sector_fund_flow >> /var/log/fundflow/fetch.log 2>&1
```

命令本身会过滤午休、收盘后、周末和法定节假日。生产环境请设置真实的 `SECRET_KEY`、`DEBUG`、`ALLOWED_HOSTS`、CORS 配置，并将数据库和缓存替换为受管 PostgreSQL、Redis。
