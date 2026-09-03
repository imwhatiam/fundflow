#!/bin/bash
# 开盘啦 App 停止抓包脚本 —— BlueStacks Air 版
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADB="${ADB_BIN:-adb}"
ADB_PORT="${ADB_PORT:-5555}"
PID_FILE="/tmp/mitm_capture.pid"
CAPTURES_DIR="$SCRIPT_DIR/captures"

echo "=========================================="
echo "  停止开盘啦 App 抓包 (BlueStacks Air 版)"
echo "=========================================="
echo ""

echo "[1/2] 停止 mitmproxy..."
if [ -f "$PID_FILE" ]; then
    MITM_PID=$(cat "$PID_FILE")
    if ps -p $MITM_PID > /dev/null 2>&1; then
        kill $MITM_PID 2>/dev/null || true
        echo "  ✅ mitmproxy 已停止 (PID: $MITM_PID)"
    else
        echo "  ⚠️  mitmproxy 未运行"
    fi
    rm -f "$PID_FILE"
else
    MITM_PID=$(pgrep -f "mitmdump.*mitm_capture" | head -1)
    if [ -n "$MITM_PID" ]; then
        kill $MITM_PID 2>/dev/null || true
        echo "  ✅ mitmproxy 已停止 (PID: $MITM_PID)"
    else
        echo "  ⚠️  未找到运行中的 mitmproxy"
    fi
fi

echo ""
echo "[2/2] 清除 BlueStacks Air 代理配置..."
if "$ADB" connect "127.0.0.1:$ADB_PORT" 2>/dev/null | grep -q "connected"; then
    "$ADB" -s "127.0.0.1:$ADB_PORT" shell settings put global http_proxy ":0" 2>/dev/null || true
    echo "  ✅ 代理已关闭 (设备：127.0.0.1:$ADB_PORT)"
else
    echo "  ⚠️  未连上 BlueStacks Air，跳过代理清理（可以手动在模拟器设置里关掉代理）"
fi

echo ""
echo "  📁 抓包数据位置：$CAPTURES_DIR"
ls -lht "$CAPTURES_DIR"/*.json 2>/dev/null | head -5 || echo "     (无新文件)"
echo ""
ls -1 "$CAPTURES_DIR"/*.json 2>/dev/null | wc -l | xargs -I {} echo "  📈 共 {} 个 JSON 文件"
echo ""
