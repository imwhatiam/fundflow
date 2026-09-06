# 开盘啦（kaipanla）改动记录

日期：2026-09-06
范围：**仅开盘啦（kaipanla）相关的前后端**，东方财富（fundflow）除一处交叉断言外未改动。

本次会话共完成 6 项改动，按主题分组如下。所有改动均已通过测试验证（详见文末「验证结果」）。

---

## 主题一：时间刻度由 15 分钟改为 5 分钟

### 背景

开盘啦的整条时间轴由唯一常量 `SNAPSHOT_INTERVAL_MINUTES` 驱动，因此改动点高度集中。

### 改动

**`backend/kaipanla/services/trading_time.py`**

- `SNAPSHOT_INTERVAL_MINUTES`：`15` → `5`
- 函数重命名（避免 5 分钟语义下命名误导）：
  - `floor_to_15min` → `floor_to_snapshot_interval`
  - `is_15min_trading_clock` → `is_trading_clock`
- 同步更新模块及全部函数的 docstring

该函数被 3 处引用，均已同步（全部在 kaipanla 内部，不越界）：

| 文件 | 改动 |
|---|---|
| `services/snapshot_collection.py` | import + 调用 |
| `management/commands/fetch_kaipanla_sector_fund_flow.py` | import + 调用 |
| `tests.py` | import + 断言 |

**纯注释同步**（不影响行为）：`models.py`、`services/snapshot_time.py`、`services/intraday_service.py` 的 docstring。

### 关键实测数据

改后每日刻度为 **50 个**（上午 25 + 下午 25），午休从 `11:30` 直接跳 `13:00`。

```
trading_slots_for_day(2026-09-03) -> 50 个刻度
  09:30, 09:35, ... 11:30 | 13:00, 13:05, ... 15:00
```

注意：首轮改动时注释误写为「48 个点」，自查时已修正为 50。

### 东财保持隔离

东财使用独立文件 `backend/fundflow/services/trading_time.py`，其 `SNAPSHOT_INTERVAL_MINUTES` 仍为 `15`，未受影响。新增测试 `test_eastmoney_stays_on_fifteen_minute_interval` 显式交叉断言东财仍为 15，防止日后误改。

---

## 主题二：verbose_name 更新与迁移

用户明确要求后，将 `snapshot_time` 字段的显示名与 5 分钟语义对齐。

**`backend/kaipanla/models.py`**

```python
- snapshot_time = models.DateTimeField(db_index=True, verbose_name="快照时间(已按15分钟对齐)")
+ snapshot_time = models.DateTimeField(db_index=True, verbose_name="快照时间(已按5分钟对齐)")
```

**新增迁移**：`backend/kaipanla/migrations/0002_alter_kaipanlasectorfundflowsnapshot_snapshot_time.py`
（仅 `AlterField` 改 verbose_name，不动 schema 数据；已应用到 `kaipanla.sqlite3`）

按项目规范，已应用的 `0001_initial.py` 中的旧措辞**未修改**。

---

## 主题三：折线图用 5 分钟数据点 + 15 分钟标签间隔

### 问题

`components/SectorFlowChart.jsx` 是**东财与开盘啦共用的源无关组件**，硬编码了 18 个 15 分钟刻度。要让开盘啦显示 5 分钟刻度，同时保证东财行为完全不变。

### 方案：可选 prop，不复制组件

**`frontend/src/components/SectorFlowChart.jsx`**

1. 新增可选 prop `timePoints`，默认仍是原 18 点（东财不传该 prop，行为零变化）
2. `alignSeriesData` 由 2 参改为 3 参：`alignSeriesData(sourcePoints, values, targetPoints)`
   - `sourcePoints` = 后端返回的 `data.time_points`（只到已到达刻度）
   - `targetPoints` = 完整刻度轴（东财 18 点 / 开盘啦 50 点）
   - 未到达的时点保持 `null`（留空）
3. `xAxis.data` 与 tooltip 改用派生出的 `axis`
4. 新增可选 prop `axisLabelInterval`，控制横轴标签显示间隔，默认 `0`（东财不变）
5. 新增 `resolveAxisLabelInterval()`：把数字间隔转为函数，**强制显示最后一个刻度**并跳过倒数第二个

### 修复的一个缺陷

首版用 `interval: 3` 时出现严重问题：50 个点索引 0–49，`interval=3` 只显示到索引 48（14:55），而**收盘 15:00（索引 49）被跳过**——最关键的刻度反而丢了。

修复后标签序列（17 个）：

```
09:30 09:45 10:00 ... 11:15 11:30 | 13:00 13:15 ... 14:30 14:45 15:00
```

其中 14:55 被主动跳过，避免与 15:00 标签挤压。

### 开盘啦侧

**`frontend/src/features/kaipanla-flow/constants.js`**

```js
export function buildKaipanlaTimePoints(intervalMinutes = 5) { ... }
export const KPL_TRADING_TIME_POINTS = buildKaipanlaTimePoints(5);  // 50 个点
export const KPL_AXIS_LABEL_INTERVAL = 3;  // 5 分钟 × 3 = 15 分钟一个标签
```

**`frontend/src/features/kaipanla-flow/KaipanlaFlowPage.jsx`**

```jsx
<SectorFlowChart
  data={chartData}
  timePoints={KPL_TRADING_TIME_POINTS}
  axisLabelInterval={KPL_AXIS_LABEL_INTERVAL}
/>
```

---

## 主题四：单页条数 30 → 80，请求数 9 → 4

### 上游实测（非估算）

逐值探测 `st`（单页条数）参数：

| `st` | 实际返回 |
|---|---|
| 30 / 50 / 60 / 70 / **80** | 按请求值正常返回 |
| **81** 及以上 | **静默只返回 8 条**（`errcode` 仍为 `0`，不报错） |

上限精确落在 **80**。一次请求拿全部 270 条做不到，4 个请求已是理论最小值。

### 改动

**`backend/kaipanla/services/constants.py`**

```python
KAIPANLA_RANKING_PAGE_SIZE = 30  →  80
```

注释中记录了已验证的上限与截断行为。

**`backend/kaipanla/services/ranking_fetcher.py`**

1. 新增**短页检测**：若还有未覆盖数据（`page × 页大小 < Count`）却收到少于请求条数的页，判定被截断 → 整次抓取失败 → **不写库**
2. 4 处重复的失败结果构造收敛为 `_failure()` 辅助方法

### 为什么要加短页检测

`st≥81` 时上游不报错、`errcode` 仍为 `0`，只是悄悄给 8 条。原代码会照常判定「抓取成功」，把只含约 32 个板块的**残缺快照写进库并标记为完整**——这是静默数据污染，比抓取失败危险得多。加上检测后，即便将来上游下调上限，也只会 loudly fail 并打 ERROR 日志。

### 实测效果（真实上游）

```
页大小 30: 9 个请求  Index=0,30,60,90,120,150,180,210,240
页大小 80: 4 个请求  Index=0,80,160,240        耗时 1.34 秒

板块数 270（一致）| 板块集合完全一致 ✓ | 逐字段值差异 0 条 ✓ | 时间戳一致 ✓
```

| 场景 | 请求数/交易日 |
|---|---|
| 原（15 分钟采集 + 每页 30） | 162 |
| 5 分钟采集 + 每页 30 | 450 |
| **5 分钟采集 + 每页 80** | **200** |

---

## 主题五：删除开盘啦的 stale 机制

### 背景

用户明确：不需要「数据可能不是最新」的判断和显示；只需「命令抓数据 → 存库 → 前端展示」，缺刻度时用前一刻度数据。

原本 `is_stale` 要求**时间轴上每一个刻度都有真实数据，缺一个就 stale**。改成 5 分钟后变成「50 个刻度一个都不能缺」，且历史数据（按 15 分钟采集，每天仅 18 个刻度）会**永久 stale**。实测库中 23 个交易日全部 stale。

### 删除内容

**后端**

| 文件 | 删除内容 |
|---|---|
| `services/intraday_builders.py` | `is_stale()`、`build_status_by_time()`；两处 payload 返回值去掉 `stale` 键；`resolve_source_time` 不再接收 `status_by_time`、不再返回 `source_stale`；`build_values_by_sector` 不再返回 `available_times` |
| `services/intraday_service.py` | 去掉 `load_intraday_status_rows` 的 import 与调用 |
| `services/intraday_queries.py` | 删除 `load_intraday_status_rows()` 及其模型 import |
| `management/commands/fetch_kaipanla_sector_fund_flow.py` | 失败提示去掉 stale 措辞 |

**前端** `features/kaipanla-flow/KaipanlaFlowPage.jsx`：删除 `stale` 计算与两处徽章。

### 明确保留

- **`resolve_source_time()`** —— 它的真正职责是选出「最近一个有数据的刻度」来决定排行榜显示哪些板块，删掉就没有板块来源了
- **`build_series_item()` 的前向填充** —— 用户要的「缺刻度用前一刻度数据」**本来就是现成行为，未做修改**
- **状态表模型与写入** —— 它在 Django admin 注册，是「该刻度抓没抓到」的唯一记录，排查有用；删模型需新增迁移。只去掉了读取路径的查询
- **东财的 stale** —— 完全未动

### 一个实测发现

```
状态行总数 414，fetch_succeeded=True 414，False 0
有状态行但无快照的刻度 0；有快照但无状态行的刻度 0
```

结构上不可能出现 `False`：`fetch_succeeded = bool(rows_by_code)` 与 `rows` 非空完全等价，而 `save_kaipanla_snapshot` 在 `rows` 为空时直接 return。因此被删掉的「跳过失败刻度」判断本来**永远不会触发**。

### 行为变化（需知悉）

删除后，以下三种情况均表现为「安静的空图或平线」，无任何提示：

1. cron 挂了 / 上游挂了
2. 查了非交易日 / 库里无数据
3. 盘中某次抓取失败

`stale` 此前是唯一能区分它们的信号。需依靠日志或 cron 输出监控。

---

## 主题六：修复默认库的孤儿迁移记录

### 现象

启动后端时 `runserver` 报 **「You have 1 unapplied migration(s)」**。

### 根因

默认库 `db.sqlite3` 中存在一条孤儿记录 `kaipanla.0001_initial`（早于数据库路由存在的历史遗留），但开盘啦的表实际只在 `kaipanla.sqlite3`。新增 `0002` 后，默认库认为 0002 未应用，而 `KaipanlaRouter.allow_migrate` 又禁止开盘啦迁移落到默认库——**永远无法真正应用**。

### 处理过程

第一次尝试直接删除该记录，结果反而让 0001 + 0002 都变成未应用（方向错误）。正确解法是反向标记：

```bash
python manage.py migrate kaipanla --fake --database=default
```

只记录不执行 SQL，默认库依然没有任何开盘啦表。

改动前已备份：`backend/db.sqlite3.bak.20260906_205204`

### ⚠️ 后续注意

**每新增一个开盘啦迁移，都要对默认库补一次 `--fake`**，否则 runserver 会持续告警。

---

## 完整文件清单

| 文件 | 改动类型 | 主题 |
|---|---|---|
| `backend/kaipanla/services/trading_time.py` | 修改 | 一 |
| `backend/kaipanla/services/snapshot_collection.py` | 修改 | 一 |
| `backend/kaipanla/management/commands/fetch_kaipanla_sector_fund_flow.py` | 修改 | 一、五 |
| `backend/kaipanla/services/snapshot_time.py` | 注释 | 一 |
| `backend/kaipanla/services/intraday_service.py` | 修改 | 一、五 |
| `backend/kaipanla/models.py` | 修改 | 一、二 |
| `backend/kaipanla/migrations/0002_*.py` | **新增** | 二 |
| `frontend/src/components/SectorFlowChart.jsx` | 修改 | 三 |
| `frontend/src/features/kaipanla-flow/constants.js` | 修改 | 三 |
| `frontend/src/features/kaipanla-flow/KaipanlaFlowPage.jsx` | 修改 | 三、五 |
| `backend/kaipanla/services/constants.py` | 修改 | 四 |
| `backend/kaipanla/services/ranking_fetcher.py` | 修改 | 四 |
| `backend/kaipanla/services/intraday_builders.py` | 修改 | 五 |
| `backend/kaipanla/services/intraday_queries.py` | 修改 | 五 |
| `backend/kaipanla/tests.py` | 修改 | 全部 |
| `README.md` | 文档同步 | 一、四、五 |

统计：`16 files changed, 306 insertions(+), 133 deletions(-)`（不含新增迁移文件的 18 行）

---

## 测试改动

新增 **11 个**测试用例（`backend/kaipanla/tests.py`，共 142 增 / 27 删）：

**新增类 `KaipanlaTradingTimeTests`（7 个）** —— 锁定 5 分钟刻度行为
- `test_day_has_fifty_five_minute_slots`
- `test_slots_are_five_minutes_apart_and_skip_lunch_break`
- `test_floor_aligns_down_to_five_minutes`
- `test_slots_until_returns_only_elapsed_ticks`
- `test_slots_until_returns_whole_day_for_past_dates`
- `test_slots_until_returns_empty_for_future_dates`
- `test_eastmoney_stays_on_fifteen_minute_interval`（防误改东财的交叉断言）

**`KaipanlaRankingFetcherTests` 新增 3 个** —— 锁定页大小 80 与短页检测
- `test_full_universe_uses_fewer_requests_than_legacy_page_size`
- `test_short_page_fails_instead_of_writing_partial_data`
- `test_page_size_stays_within_verified_upstream_limit`

**改写 1 个** —— 原 `test_missing_tick_is_stale` 改为 `test_falls_back_to_previous_tick_when_latest_is_missing`，直接断言前向填充结果 `[1.0, 1.0]`，把「缺刻度用前一刻度」这个行为锁住。

另有约 10 处 `stale` 断言随主题五删除。

---

## 验证结果

### 后端

```
python manage.py test fundflow kaipanla
Ran 83 tests in 23.321s  →  OK

python manage.py makemigrations --check --dry-run  →  无漂移
```

### 前端

```
npm run lint   →  0 错误
npm run build  →  成功
```

### 端到端（实际启动服务）

后端 `http://localhost:8000`，前端 `http://localhost:5173`：

| 检查项 | 结果 |
|---|---|
| 单日 API 顶层键 | `['trade_date', 'time_points', 'series']` — 无 stale |
| 单日数据 | 50 个刻度 `09:30→15:00`，6 条曲线，每条 50 点（前向填充正常） |
| 历史 API（5 天） | 5 天全部有 `15:00` 数据，无 stale |
| 前端下发的开盘啦模块 | `stale` 出现 0 次 |
| 东财页面 | `stale` 保留（符合预期） |
| CORS | `access-control-allow-origin: http://localhost:5173` ✓ |

---

## 遗留事项

1. **共享文档仍有滞后**：`README.md` 第 8、16 行等处仍写「两个源共享 18 个 15 分钟刻度」类表述。因当时要求「只改开盘啦前后端」，未改动这些共享段落。

2. **`BlueStacks-kaipanla/README.md:94`** 的「不能替代当前产品的 15 分钟板块快照」措辞含糊。该目录与主产品解耦，优先级低。（同目录另两处提到的 `fundflow` 指东财，仍是 15 分钟，**不算过期**）

3. **`KPL_AXIS_LABEL_INTERVAL = 3` 是隐式耦合**：语义为「3 × 5 分钟 = 15 分钟」。若将来再改刻度间隔，这个 `3` 会静默失准。可改为从间隔推导（如 `15 / 5`）。

4. **缓存 TTL 变短**：`intraday_cache.py` 按「下一刻度」失效，刻度间隔 15 → 5 分钟后服务端缓存命中时间相应缩短，上游请求量上升。

5. **历史数据每日仅 18 个刻度**：改为 5 分钟采集后，历史日仍只有 18 个点，会被前向填充为 50 个点显示。数值正确（15:00 收盘值准确），但曲线精度低于新采集的数据。

6. **前导缺失填 0**：`build_series_item` 中 `last_value` 初值为 `0.0`，因此 09:30 无数据、09:35 才有数据时，09:30 会画成 0 而非留空。实际很少触发。

---

## 运维建议（5 分钟定时采集）

推荐 crontab：

```cron
# 交易时段每 5 分钟采集（命令自行判断交易时段与法定节假日，非交易时段直接退出）
*/5 9-15 * * 1-5 cd /Users/lian/fundflow/backend && flock -n /tmp/fetch_kaipanla.lock ./venv/bin/python manage.py fetch_kaipanla_sector_fund_flow >> /var/log/kpl_fetch.log 2>&1

# 收盘后兜底补 15:00 刻度
7 15 * * 1-5 cd /Users/lian/fundflow/backend && flock -n /tmp/fetch_kaipanla.lock ./venv/bin/python manage.py fetch_kaipanla_sector_fund_flow --latest >> /var/log/kpl_fetch.log 2>&1
```

要点：
- `flock` 为 `AGENTS.md` 明确要求，防止任务重叠
- 单次抓取实测 **21 秒**（含 Django 启动），最坏 48 秒，远小于 5 分钟
- `floor_to_snapshot_interval` 向下取整，crontab 抖动有 5 分钟容错窗口
- 节假日由 `chinese-calendar` 自动跳过
- 历史端点（5/10/20 天视图）依赖每日 `15:00`，建议保留收盘兜底任务
