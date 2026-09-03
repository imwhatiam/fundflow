#!/bin/bash
# 开盘啦 App 抓包脚本 —— BlueStacks Air (Apple Silicon Mac) 版
# 用法：
#   ./start_capture_bluestacks.sh
#   ADB_PORT=5575 PROXY_HOST=192.168.64.1 ./start_capture_bluestacks.sh   # 如果默认值不对，用环境变量覆盖
#
# 和原版 start_capture.sh 的区别：
#   1. 不再假设 MuMu 的固定 adb 路径，改用系统里的 adb（brew install android-platform-tools）
#   2. 不再假设固定端口列表，ADB_PORT 从 BlueStacks Air 设置里的 ADB 页面读
#   3. 不再假设网关一定是 10.0.2.2，PROXY_HOST 需要你自己验证（见下方说明）
#   4. mitm_capture.py 就在项目根目录，不在 scripts/ 子目录下

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MITM_SCRIPT="$SCRIPT_DIR/mitm_capture.py"

ADB="${ADB_BIN:-adb}"
ADB_PORT="${ADB_PORT:-5555}"          # BlueStacks Air 设置 → 高级 → Android Debug Bridge 里显示的端口
PROXY_HOST="${PROXY_HOST:-10.0.2.2}"  # ⚠️ 不保证对 BlueStacks Air 有效，见下方“如何确认网关”
PROXY_PORT="${PROXY_PORT:-8080}"

echo "=========================================="
echo "  开盘啦 App 抓包工具 (BlueStacks Air 版)"
echo "=========================================="
echo ""

# 0. 检查 adb 是否可用
if ! command -v "$ADB" >/dev/null 2>&1; then
    echo "❌ 找不到 adb 命令。"
    echo "   建议: brew install --cask android-platform-tools"
    echo "   或者设置 ADB_BIN=/path/to/adb 重新运行本脚本"
    exit 1
fi

if [ ! -f "$MITM_SCRIPT" ]; then
    echo "❌ 错误：mitm_capture.py 不存在：$MITM_SCRIPT"
    exit 1
fi

# 1. 重启 ADB 服务器
echo "[1/5] 重启 ADB 服务器..."
"$ADB" kill-server 2>/dev/null || true
"$ADB" start-server 2>/dev/null
sleep 1

# 2. 连接 BlueStacks Air
echo "[2/5] 连接 BlueStacks Air (127.0.0.1:$ADB_PORT)..."
if ! "$ADB" connect "127.0.0.1:$ADB_PORT" 2>/dev/null | grep -q "connected"; then
    echo "❌ 连接失败。请确认："
    echo "   1) BlueStacks Air 已打开"
    echo "   2) 设置 → 高级 → Android Debug Bridge (ADB) 已开启"
    echo "   3) 上面显示的端口号和 ADB_PORT=$ADB_PORT 一致（不一致就用 ADB_PORT=xxxx 重新运行）"
    exit 1
fi
DEVICE="127.0.0.1:$ADB_PORT"
echo "  ✅ 已连接：$DEVICE"

# 2.5 打印网关信息，帮助确认 PROXY_HOST 是否正确
echo ""
echo "  ℹ️  当前 PROXY_HOST=$PROXY_HOST，如果稍后 App 无法联网/mitmproxy 抓不到包，"
echo "     用下面命令查看 BlueStacks Air 内部看到的默认网关，换成那个地址重跑本脚本："
echo "     $ADB -s $DEVICE shell ip route"
echo ""

# 3. 清除旧代理
echo "[3/5] 清除旧代理配置..."
"$ADB" -s "$DEVICE" shell settings put global http_proxy ":0" 2>/dev/null || true
sleep 0.5

# 4. 启动 mitmproxy（后台运行）
echo "[4/5] 启动 mitmproxy (端口 $PROXY_PORT)..."
cd "$SCRIPT_DIR"
pkill -f "mitmdump.*mitm_capture" 2>/dev/null || true
sleep 1

nohup mitmdump -s "$MITM_SCRIPT" --listen-port "$PROXY_PORT" > /tmp/mitm_capture.log 2>&1 &
MITM_PID=$!
echo $MITM_PID > /tmp/mitm_capture.pid
sleep 2

if ! ps -p $MITM_PID > /dev/null 2>&1; then
    echo "❌ 错误：mitmproxy 启动失败"
    cat /tmp/mitm_capture.log
    exit 1
fi

# 5. 配置代理
echo "[5/5] 配置 BlueStacks Air 代理 → $PROXY_HOST:$PROXY_PORT..."
"$ADB" -s "$DEVICE" shell settings put global http_proxy "$PROXY_HOST:$PROXY_PORT"
PROXY_SETTING=$("$ADB" -s "$DEVICE" shell settings get global http_proxy 2>/dev/null | tr -d '\r\n')

echo ""
echo "=========================================="
echo "  ✅ 抓包环境已就绪！"
echo "=========================================="
echo "  mitmproxy PID : $MITM_PID"
echo "  代理地址      : $PROXY_HOST:$PROXY_PORT (已写入: $PROXY_SETTING)"
echo "  模拟器设备    : $DEVICE"
echo "  数据保存      : $SCRIPT_DIR/captures/"
echo ""
echo "  📱 首次使用还需要装 mitmproxy 的 CA 证书（否则 HTTPS 请求会失败）："
echo "     1. 在 BlueStacks Air 里打开浏览器访问 http://mitm.it"
echo "     2. 下载并安装 Android 证书（跟着提示走）"
echo "     3. 如果安装后 App 里仍然报网络错误/mitmproxy 日志里全是 TLS 失败，"
echo "        说明开盘啦这个 App 只信任系统级 CA，这种情况下必须先给"
echo "        BlueStacks Air 的实例开 root（BlueStacks Air 默认不带 root），"
echo "        再把证书装进系统信任区"
echo ""
echo "  📱 证书装好后，在 BlueStacks Air 里打开 开盘啦 App 并正常浏览（行情/板块/个股页面）"
echo ""
echo "  🛑 停止抓包：./stop_capture_bluestacks.sh"
echo "  📊 实时日志：tail -f /tmp/mitm_capture.log"
echo "  📁 最新抓包：ls -lht $SCRIPT_DIR/captures/*.json | head -10"
echo ""
