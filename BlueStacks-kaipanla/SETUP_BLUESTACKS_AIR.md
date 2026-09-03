# 在 BlueStacks Air 上跑通开盘啦资金流抓取

这份指南只覆盖「抓资金流数据」这一条链路，原项目里 267 个概念板块走 Socket+Protobuf 那部分（用于拿量比/机构增仓）**不需要**，可以完全跳过——`主力净额`（也就是资金流）全部走普通 HTTPS 接口，`GetPlate_Info_QJ`（板块）、`ZhiShuStockList_W8`（个股）都能拿到。

## 0. 前置安装（Mac 上）

```bash
brew install --cask android-platform-tools   # 装 adb
pip install --break-system-packages requests pandas akshare mitmproxy
```

## 1. 在 BlueStacks Air 里开 ADB

设置 → 高级（Advanced）→ 打开 "Android Debug Bridge (ADB)"，会显示一个端口号（不一定是 5555，记下来）。

## 2. 确认两个"未知数"

原项目的脚本是照着 MuMu 模拟器写死的（固定 adb 路径、固定网关 10.0.2.2）。BlueStacks Air 底层是 Apple 的 Virtualization Framework，不是 MuMu 用的 QEMU，**网关地址不一定还是 10.0.2.2**，需要自己确认一遍：

```bash
adb connect 127.0.0.1:<上一步看到的端口>
adb -s 127.0.0.1:<端口> shell ip route
# 找 "default via X.X.X.X" 这一行，X.X.X.X 就是 Mac 主机在模拟器里的地址
```

把这个地址记下来，等下作为 `PROXY_HOST` 传给抓包脚本。

## 3. 启动抓包

```bash
chmod +x start_capture_bluestacks.sh stop_capture_bluestacks.sh
ADB_PORT=<你的端口> PROXY_HOST=<第2步查到的网关> ./start_capture_bluestacks.sh
```

## 4. 装 mitmproxy 证书（关键，容易卡住的一步）

1. 代理配好之后，在 BlueStacks Air 内置浏览器里访问 `http://mitm.it`，下载并安装 Android 证书。这一步不需要 root，装的是"用户级"证书。
2. 打开开盘啦 App，正常浏览行情/板块/个股页面。
3. 看 `/tmp/mitm_capture.log`：
   - 如果能看到 `apphwshhq.longhuvip.com` / `apphis.longhuvip.com` 这些请求正常返回 200，说明成功了，跳到第 5 步。
   - 如果全是 TLS handshake 失败，说明这个 App（和原作者在 MuMu 上遇到的情况一样）不认"用户级"证书，必须让证书进系统信任区，这就需要 root。BlueStacks Air 默认不像 MuMu 那样自带 root，需要额外工具（例如社区维护的 BlueStacks-Root-GUI 之类项目，专门支持 Apple Silicon 的 BlueStacks Air）先把实例 root 掉，再把证书 push 到 `/system/etc/security/cacerts/`。这一步风险自行评估，root 之后设备安全性会下降。

## 5. 从抓包数据里拿 UserID / Token

```bash
grep -l "Token=" captures/*.json | tail -1 | xargs cat | python3 -c "
import sys, json
d = json.load(sys.stdin)
body = d['request_body']
for part in body.split('&'):
    if part.startswith('Token=') or part.startswith('UserID='):
        print(part)
"
```

把拿到的值填进 `.env`（参考 `.env.example`）：

```
KPL_USER_ID=xxxxx
KPL_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KPL_DEVICE_ID=80ca7d1b-2a24-3cd0-a915-99b61f6f88aa
```

`DeviceID` 随便留成脚本里默认那个固定值就行，App 服务端似乎并不严格校验它和 UserID/Token 是否匹配（原作者也是这么用的）。

## 6. 停止抓包，跑批量爬虫

```bash
./stop_capture_bluestacks.sh
python3 crawler_batch.py --start 2026-08-01 --end 2026-08-26
```

对 `crawler_batch.py` 相对原始版本做了两处修复（原始版本直接运行会崩溃）：

1. `ROOT = os.path.dirname(...)` 返回的是字符串，原代码后面用 `ROOT / ".env"` 这种写法会直接 `TypeError`（字符串不支持 `/` 运算）。改成了 `pathlib.Path`。
2. `refresh_token()` 里给 `TOKEN`/`USER_ID` 赋值时没声明 `global`，导致 token 刷新后主流程用的还是旧值。加上了 `global` 声明。

因为自动刷新这条链路依赖你已经手动跑过一次抓包（第 3-5 步），建议**第一次先手动填好 `.env` 再跑**，不要依赖脚本自动拉起 mitmproxy——自动那条路径在 BlueStacks Air 上还是要你自己去 App 里点一点产生流量，体验上和手动做区别不大。

## 7. 产出

- `data/main_plate_info_{date}.csv`：板块资金流（主力净额）+ 涨停封单等
- `data/stock_info_{date}.csv`：个股资金流（主力买/卖/净额）等 60+ 字段
- `data/sub_plate_info_{date}.csv`：板块-子板块关系（资金流分析用不上，可以忽略）

## 补充说明

- 这套接口是开盘啦 App 的私有/未公开接口，走的是账号 Token 鉴权。请求量大、并发高会有被限流或封号的风险，脚本里默认的并发（`--workers`）和延时（`--delay`）建议不要调得太激进，尤其是长时间跑批量历史数据的时候。
- Token 有效期有限，过期后要重复第 3-5 步重新抓一次。

## 8. 导出与 fundflow 兼容的个股资金流快照

`fundflow_adapter.py` 将 `ZhiShuStockList_W8` 的数组响应映射为与
`backend/fundflow/services/eastmoney_client.py` 相同的 JSONL 字段名：

```bash
# 先用已有 CSV 验证映射，不发任何网络请求
python3 fundflow_adapter.py \
  --input-csv data/stock_info_2026-05-06.csv \
  --date 2026-05-06

# 只抓少量板块，验证 BlueStacks Air 抓到的 Token 和历史日接口
python3 fundflow_adapter.py --date 2026-08-25 --max-plates 1 --types 6
```

输出文件是 `data/fundflow_stock_fund_flow_YYYY-MM-DD.jsonl`，每行一个 JSON
对象，包含 `stock_code`、`stock_name`、`market`、`latest_price`、`change_pct`、
`turnover_amount`、`main_net_inflow`、`main_net_inflow_ratio` 等字段。金额单位为元。

开盘啦的 `ZhiShuStockList_W8` 未提供成交量及超大/大/中/小单拆分，因此 JSON 中的
`volume`、`super_large_net_inflow`、`large_net_inflow`、`medium_net_inflow` 和
`small_net_inflow` 都是 `null`；脚本不会伪造这些值。

默认 `--types 6` 请求量较低，但可能不包含全市场每只股票。`--types all` 会遍历
`Type=0..19`，按当前约 733 个子板块估计可能发起约 14,660 个请求，因此必须显式确认：

```bash
python3 fundflow_adapter.py \
  --date 2026-08-25 \
  --types all \
  --allow-high-request-volume \
  --delay 0.25
```

该高请求量模式不适合 15 分钟定时任务；在将开盘啦作为 fundflow 的生产数据源之前，
应先对输出的唯一股票数设置覆盖阈值并评估其限流策略。

> **当前日期限制（已在 2026-08-26 验证）**：这个适配器使用的
> `apphis.longhuvip.com` / `RealRankingInfo` + `ZhiShuStockList_W8` 是历史日链路；
> 当传入当天 `2026-08-26` 时，服务端返回 `errcode=1020`（参数出错）。因此它不能直接
> 替代 fundflow 每 15 分钟的实时任务。若要接入实时快照，请保持抓包开启，在开盘啦 App
> 中打开一只股票并进入资金流页面，记录该页面新出现的请求域名、`c`、`a` 和非敏感参数名，
> 再基于真实请求另行实现实时客户端。
