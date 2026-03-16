#!/bin/sh
# =============================================================
# Misaka MediaFlow Docker Entrypoint
#
# 功能:
#   1. 修复 volume 挂载后的目录权限 (以 root 执行)
#   2. 用 su-exec 降权到 appuser 启动应用
#
# 对齐弹幕库 exec.sh 方案
# =============================================================

set -e

CONFIG_DIR="${MISAKAMF_CONFIG_DIR:-/app/config}"

# ---- 以 root 身份修复 volume 权限 ----
for dir in "$CONFIG_DIR" "$CONFIG_DIR/logs" "$CONFIG_DIR/strm"; do
    mkdir -p "$dir" 2>/dev/null || true
done
chown -R appuser:appgroup /app/config 2>/dev/null || true

# ---- 用 su-exec 降权到 appuser 启动应用 ----
exec su-exec appuser uvicorn src.main:app --host 0.0.0.0 --port 7789 --log-level info

