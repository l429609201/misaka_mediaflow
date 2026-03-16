#!/bin/sh
# =============================================================
# Misaka MediaFlow Docker Entrypoint
#
# 功能:
#   1. 修复 volume 挂载后的目录权限 (以 root 执行)
#   2. 用 su-exec 降权到 mediaflow 启动应用
#
# 对齐弹幕库 exec.sh 方案
# =============================================================

set -e

CONFIG_DIR="${MISAKAMF_CONFIG_DIR:-/app/config}"
APP_PORT="${MISAKAMF_SERVER__PORT:-7789}"
LOG_LEVEL="${MISAKAMF_SERVER__LOG_LEVEL:-info}"

# ---- 以 root 身份修复 volume 权限 ----
for dir in "$CONFIG_DIR" "$CONFIG_DIR/logs" "$CONFIG_DIR/strm"; do
    mkdir -p "$dir" 2>/dev/null || true
done
chown -R mediaflow:mediaflow /app/config 2>/dev/null || true

# ---- 用 su-exec 降权到 mediaflow 启动应用 ----
exec su-exec mediaflow python -m uvicorn src.main:app --host 0.0.0.0 --port "$APP_PORT" --log-level "$LOG_LEVEL"

