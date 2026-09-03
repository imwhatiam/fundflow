# BlueStacks-kaipanla 工作指南

## 范围与边界

此目录是 BlueStacks Air 上的开盘啦 App 抓包、凭据维护及历史离线转换工具。它不属于当前 Django/React 产品的正式采集运行时。

- 正式开盘啦板块采集代码在 `../backend/kaipanla/`，并且仅处理当前的 sector 数据契约。
- `crawler_batch.py` 与 `fundflow_adapter.py` 是历史/个股离线工具。不得借此重新引入主产品已移除的股票模型、接口、CSV 同步、前端或自动轮询。
- `README.md` 和仓库根目录的 `README.md`、`AGENTS.md` 是当前范围的说明来源；`SETUP_BLUESTACKS_AIR.md` 只作历史补充。

## 凭据、抓包和本地数据

`.env`、`captures/`、`data/`、JSONL/CSV 输出及任何请求正文均按机密处理，可能包含 `KPL_USER_ID`、`KPL_TOKEN`、`KPL_DEVICE_ID` 和账号/会话元数据。

- 只处理你获授权的账号、设备和流量。
- 禁止提交、上传、粘贴或在日志、测试、截图、文档和最终回复中回显真实凭据或完整抓包内容。
- 使用 `.env.example` 作为格式模板；真实 `.env` 仅保存在本机，并设置最小必要文件权限。
- 新增测试使用脱敏、合成夹具；禁止录制真实 HTTP 流量或使用真实 Token。
- `captures/` 与 `data/` 必须保持本地、未跟踪。若将来调整忽略规则，先确认不会把已有敏感文件纳入版本控制。

## 抓包脚本约束

- `start_capture_bluestacks.sh` 的职责是 ADB 连接、mitmdump 生命周期和 Android 全局代理配置；`stop_capture_bluestacks.sh` 的职责是停止代理并清理该全局代理。修改其中任一脚本时，优先保证失败路径也不会让模拟器长期保留代理配置。
- 默认 `PROXY_HOST=10.0.2.2` 并非 BlueStacks Air 的保证地址。排障时以 `adb ... shell ip route` 的模拟器网关为准，不要把某台机器的地址硬编码为通用值。
- `mitm_capture.py` 只应保存完成响应的白名单流量，并继续将输出放在 `captures/`。扩大域名范围、保存更多 header/cookie 或启用响应篡改前，必须先有明确需求、授权和安全评审。
- 不得通过禁用证书校验、修改 App、伪造 IP/身份、规避限流或其他访问控制来让抓包工作。用户级证书不能满足需求时，应停止并评估风险，而非将 system/root 级改动常规化。
- 每次人工抓包结束后运行 `./stop_capture_bluestacks.sh`；若 ADB 断开，明确提示并手动确认模拟器代理已关闭。

## 上游请求纪律

- 开盘啦接口属于非公开 App 集成。避免并发扩大、频率提高、无限重试和批量扫描。
- `crawler_batch.py` 已含历史批抓取、随机延时、重试与线程池；不要把它当作当前 Kaipanla 板块服务的实现范本，也不要默认运行它。
- `fundflow_adapter.py --types all` 的高请求量保护必须保留。优先使用 `--input-csv` 的无网络转换；真实请求需显式、最小化且只在已授权的维护场景执行。
- 当前 `backend/kaipanla` 的 `RealRankingInfo` 串行分页、凭据环境变量和快照语义由根目录 `AGENTS.md` 约束；这里的旧历史端点不能替代它。

## 代码组织与变更原则

- 保持职责分离：shell 脚本管理本地代理/ADB，`mitm_capture.py` 负责捕获序列化，解析/离线导出逻辑留在 Python 工具中。
- Python 使用四空格缩进、`snake_case`；shell 脚本使用 `set -e`，引用变量并在有副作用的失败路径提供清理策略。
- 不要把 Token 写入源代码、默认参数、命令行示例、断言或异常消息。更新 `.env` 的代码不得打印完整值。
- 修改解析字段、历史请求参数、限流/重试、并发、抓包白名单或代理生命周期时，先增加聚焦的无网络回归测试，并更新本目录 README 中相应约束。
- 不在无明确需求时编辑 `SETUP_BLUESTACKS_AIR.md` 的历史记录；如它与当前范围冲突，在新文档中说明边界，而不是把旧个股流程恢复为产品功能。

## 验证与交付

在本目录完成非联网验证：

```bash
bash -n start_capture_bluestacks.sh stop_capture_bluestacks.sh
python3 -m unittest -v test_fundflow_adapter
```

如改动会影响仓库其余部分，还应按根目录指南运行相应后端/前端检查，以及：

```bash
git diff --check
```

真实抓包不是自动化测试。若为排障而执行，应使用自己的授权环境、最少请求、不得记录到提交内容，并在结束时清理 Android 代理。
