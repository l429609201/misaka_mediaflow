#!/bin/bash
# go-proxy/build.sh — 一键构建 Go 反代可执行文件
# 用法: bash build.sh
# 产出: go-proxy/go-proxy

set -e

VERSION="1.0.0"
cd "$(dirname "$0")"

echo "=== Misaka MediaFlow Go Proxy 构建 ==="
echo "版本: $VERSION"

# 检查 Go 环境
if ! command -v go &> /dev/null; then
    echo "错误: 未找到 Go 编译器，请先安装 Go (https://go.dev/dl/)"
    exit 1
fi
echo "Go 版本: $(go version)"

# 下载依赖
echo ""
echo "[1/2] 下载依赖..."
go mod tidy

# 构建
echo "[2/2] 编译中..."
CGO_ENABLED=0 go build -ldflags "-s -w -X main.Version=${VERSION}" -o go-proxy ./cmd/proxy/

SIZE=$(du -h go-proxy | cut -f1)
echo ""
echo "构建成功!"
echo "  文件: $(pwd)/go-proxy ($SIZE)"
echo "  版本: $VERSION"

