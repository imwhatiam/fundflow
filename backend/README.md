# 后端运行说明

后端只维护东方财富行业板块资金流快照。

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py fetch_sector_fund_flow
python manage.py runserver 8000
```

`fetch_sector_fund_flow` 仅在 A 股交易时段抓取并写入 15 分钟刻度。交易日判断使用 `chinese-calendar` 过滤法定节假日，调休周末仍按休市处理。

在非交易时段，正常命令直接退出；需要初始化或恢复一份最近可用快照时执行：

```bash
python manage.py fetch_sector_fund_flow --latest
```

生产定时任务示例：

```cron
*/15 9-15 * * 1-5 cd /path/to/backend && /path/to/venv/bin/python manage.py fetch_sector_fund_flow >> /var/log/fundflow/fetch.log 2>&1
```

命令本身会过滤午休、收盘后、周末和法定节假日。生产环境请设置真实的 `SECRET_KEY`、`DEBUG`、`ALLOWED_HOSTS`、CORS 配置，并将数据库和缓存替换为受管 PostgreSQL、Redis。
