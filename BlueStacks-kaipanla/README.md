# BlueStacks Air 开盘啦抓包与凭据维护

此目录用于在**你本人有权使用的开盘啦 App 账号和 BlueStacks Air 实例**中，通过 ADB 配置本机 mitmproxy 代理，采集 App 发出的请求，以便更新本地所需的 `KPL_USER_ID`、`KPL_TOKEN` 和（如请求中变更）`KPL_DEVICE_ID`。

它是本地维护/排障工具目录，**不是**当前 Django 产品的采集运行时。当前面向板块资金流的正式实现位于 [`../backend/kaipanla/`](../backend/kaipanla/)；不要将本目录的历史个股导出工具接回现有的 sector-only 产品流程。

## 安全、授权与范围

- 仅捕获和使用你获授权的账号、模拟器和网络流量；遵守开盘啦的服务条款及适用规则。
- `.env`、`captures/*.json`、`data/*` 和导出的 JSONL 都可能含有账号凭据、设备标识、请求参数或市场数据。它们必须留在本机，禁止提交、共享、上传至工单/聊天记录或写入测试夹具。
- 不要在终端输出、日志、截图或文档中暴露完整 `UserID`、`Token`、`DeviceID` 或 `request_body`。
- 本目录不用于规避 TLS 校验、访问控制、限流或其他平台保护机制。抓包失败时应先停止并检查本机代理、路由和授权环境；不要通过修改 App 或关闭安全校验来继续。
- 凭据可能过期。发生认证失败时，重新按本目录流程进行一次受控抓包并更新本地环境即可；不要增加并发或请求频率来反复尝试。

## 文件职责

| 文件/目录 | 职责 | 是否属于当前正式板块运行时 |
| --- | --- | --- |
| `start_capture_bluestacks.sh` | 连接 BlueStacks Air ADB、启动 `mitmdump`，并把 Android 全局 HTTP 代理指向本机代理。 | 否，本地维护工具 |
| `stop_capture_bluestacks.sh` | 停止记录的 `mitmdump` 进程，并尝试清空模拟器全局代理。 | 否，本地维护工具 |
| `mitm_capture.py` | mitmproxy add-on；只保存主机名包含 `longhuvip` 或 `523touzi` 的响应流。每份 JSON 含请求正文和已解析的响应正文。 | 否，本地维护工具 |
| `.env.example` | 本地凭据文件模板。复制后填写真实值，但不要提交生成的 `.env`。 | 否 |
| `crawler_batch.py` | 历史板块/个股批量抓取与 CSV 输出的旧离线工具；会读取 `.env`，并包含并行请求。 | 否，遗留辅助工具 |
| `fundflow_adapter.py` | 将旧 `stock_info` CSV 或历史接口结果转为个股 JSONL 的离线适配器。 | 否，遗留辅助工具 |
| `test_fundflow_adapter.py` | `fundflow_adapter.py` 的无网络单元测试。 | 否 |
| `SETUP_BLUESTACKS_AIR.md` | 较早的操作记录，包含历史个股导出背景；以本 README 和仓库根目录文档的当前范围说明为准。 | 否 |
| `captures/`、`data/` | 本地抓包和导出产物；按敏感数据处理。 | 否 |

`mitm_capture.py` 默认只记录白名单域名的请求，并将顺序号、时间、URL、请求正文、HTTP 状态和 JSON 响应写入 `captures/`。因此即使文件名不显眼，内容也应视为机密。

## 前置条件

在本目录执行操作前，确认：

1. BlueStacks Air 已启动，并且其设置中启用了 Android Debug Bridge（ADB）；记下界面显示的端口。
2. macOS 可运行 `adb` 和 `mitmdump`，且当前 Python 环境已安装运行 add-on 所需的 `mitmproxy`。
3. 模拟器能够访问 Mac 上的代理地址。默认 `PROXY_HOST=10.0.2.2` 只是常见值，**不保证**适用于 BlueStacks Air；应以模拟器内 `ip route` 显示的默认网关为准。
4. 已准备一个仅在本机保存的 `.env`：

   ```bash
   cp .env.example .env
   chmod 600 .env
   ```

`.env` 由旧离线脚本读取；正式 Django 后端不会自动读取这个文件，而是从进程环境读取 `KPL_USER_ID`、`KPL_TOKEN` 和 `KPL_DEVICE_ID`。请通过你安全的进程管理方式把更新后的值注入后端，切勿把它们写回仓库配置。

## 安全抓包流程

从 `BlueStacks-kaipanla/` 目录执行：

1. **启动本地代理和 Android 全局代理。** 如 ADB 端口或模拟器网关不同，可在命令前覆盖变量：

   ```bash
   ADB_PORT=5555 PROXY_HOST=10.0.2.2 ./start_capture_bluestacks.sh
   ```

   脚本会重启本机 ADB 服务、连接 `127.0.0.1:$ADB_PORT`、清理旧代理、启动 `mitmdump`，然后写入新的全局代理。启动后可用脚本提示的 `adb ... shell ip route` 核对网关；若 App 无法联网或没有抓到流量，应先停止脚本并修正 `PROXY_HOST`。

2. **在模拟器中完成常规的证书信任配置。** 首次使用时，按照 mitmproxy 的本地证书安装流程在模拟器浏览器中访问 `http://mitm.it` 并安装用户证书。部分 App 可能不信任用户证书；不要把修改系统信任库、root 模拟器或绕过证书校验当作默认步骤。若无法在受控环境内完成，应停止操作并重新评估授权与风险。

3. **在 App 中正常浏览。** 打开行情或板块页面，让属于自己账号的正常请求产生。实时日志位于 `/tmp/mitm_capture.log`，抓包文件保存在 `captures/`。

4. **仅在本机私下查看最新的相关抓包。** 找到其 `request_body` 中的 `UserID`、`Token` 和 `DeviceID`，手工填入 `.env` 对应变量。不要使用会把整段请求正文回显到终端、剪贴板共享、截图或外部服务的方式。

5. **停止并清理代理。** 完成后务必运行：

   ```bash
   ./stop_capture_bluestacks.sh
   ```

   停止脚本会结束 PID 文件记录的 mitmproxy（或查找匹配进程），并尝试将 `127.0.0.1:$ADB_PORT` 的 Android 全局代理重置为 `:0`。如果 ADB 已断开，脚本会提示手动在模拟器设置中关闭代理；确认清理后再结束工作。

### 可配置环境变量

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| `ADB_BIN` | `adb` | Android platform-tools 中 `adb` 的路径或命令名。 |
| `ADB_PORT` | `5555` | BlueStacks Air 设置中显示的本机 ADB 端口。 |
| `PROXY_HOST` | `10.0.2.2` | 从模拟器视角可访问 Mac 代理的地址；以 `ip route` 实测为准。 |
| `PROXY_PORT` | `8080` | `mitmdump` 监听端口。 |

## 凭据更新后的使用边界

- 当前板块采集命令是 `backend/manage.py fetch_kaipanla_sector_fund_flow`；它使用的是 `backend/kaipanla/` 的串行分页实现，不会调用本目录的 `crawler_batch.py` 或 `fundflow_adapter.py`。
- `crawler_batch.py` 会从 `captures/` 搜索包含 `Token=` 的文件，并能写回 `.env`。它还含有自动刷新逻辑；该路径不能代替 `start_capture_bluestacks.sh` 的 ADB、代理和证书设置。首次或异常恢复时，应优先使用上面的显式抓包流程。
- 不要把 `.env.example` 里的示例设备标识视为可公开共享的生产配置。以你获授权的请求和安全的环境变量注入为准。

## 遗留离线工具

`crawler_batch.py` 和 `fundflow_adapter.py` 保留用于历史研究与本地转换，范围与当前产品不同：

- `crawler_batch.py` 处理历史板块、子板块和个股 CSV，且默认可使用线程池并发；它不是当前实时板块采集命令的一部分。
- `fundflow_adapter.py` 处理**个股**数据：可离线转换已有 `stock_info` CSV，或走已验证的历史接口导出 JSONL。它要求显式 `--date`；`--types all` 需要 `--allow-high-request-volume` 才会执行，因为请求量可能很大。
- 已验证的历史接口不接受当天日期，不能替代当前产品的 15 分钟板块快照。不要基于该适配器重新引入股票工作流、自动轮询或高频批抓取。

如果确有离线转换需求，优先使用不发网络请求的 `--input-csv` 模式，并把输入与输出都当作本地敏感数据处理。

## 非联网验证

文档或代码变更后，可进行不触发 App 请求的检查：

```bash
bash -n start_capture_bluestacks.sh stop_capture_bluestacks.sh
python3 -m unittest -v test_fundflow_adapter
```

不要把“抓包成功”作为自动化测试；它依赖真实模拟器、证书、网络和有效凭据。涉及真实流量的检查必须显式、最小化、只读，并在完成后运行停止脚本清理代理。
