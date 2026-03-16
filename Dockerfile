# =============================================================
# Misaka MediaFlow — 四阶段 Docker 构建
#
#   1. Node    → 编译前端 (React + Vite)  [$BUILDPLATFORM 原生编译]
#   2. Go      → 编译反代 (Gin, CGO=0 静态链接)
#   3. Python  → 编译 C 扩展 (build-essential + dev headers)
#   4. Runtime → 纯运行时 (无编译器, su-exec 降权)
#
# 基底: l429609201/su-exec:su-exec (Debian slim + Python 3.11 + su-exec)
# 安全: su-exec 降权至 UID=1000 非 root 用户
# 体积: ~120MB (无 gcc/dev headers/curl, 依赖深度清理)
# =============================================================

ARG GO_VERSION=1.22
ARG BUILD_DATE
ARG VERSION=dev

# ==================== 阶段 1: 前端构建 ====================
# $BUILDPLATFORM 确保在原生架构执行, 前端产物是平台无关的
FROM --platform=$BUILDPLATFORM node:20-alpine AS web-builder

WORKDIR /build
COPY web/package.json web/package-lock.json* ./
RUN npm ci --registry=https://registry.npmmirror.com 2>/dev/null \
    || npm ci
COPY web/ .
RUN npm run build


# ==================== 阶段 2: Go 反代编译 ====================
FROM golang:${GO_VERSION}-alpine AS go-builder

WORKDIR /build
COPY go-proxy/go.mod go-proxy/go.sum ./
RUN go mod download
COPY go-proxy/ .

ARG VERSION=dev
ARG TARGETARCH

RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build \
    -ldflags "-X main.Version=${VERSION} -s -w" \
    -trimpath \
    -o /build/mediaflow-proxy \
    ./cmd/proxy/


# ==================== 阶段 3: Python 依赖编译 ====================
FROM l429609201/su-exec:su-exec AS py-builder

# 编译时依赖 (不会进入最终镜像)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libpq-dev \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install
COPY requirements.txt .

# --target: 平铺安装到 /install
# --no-compile: 不生成 .pyc (运行时 PYTHONDONTWRITEBYTECODE=1)
# find 清理: 删除测试/文档/类型桩/缓存, 大幅压缩体积
RUN pip install --no-cache-dir --no-compile -r requirements.txt --target . \
    && find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true \
    && find . -type f -name '*.pyc' -delete \
    && find . -type f -name '*.pyo' -delete \
    && find . -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null || true \
    && find . -type d -name 'tests' -exec rm -rf {} + 2>/dev/null || true \
    && find . -type d -name 'test' -exec rm -rf {} + 2>/dev/null || true \
    && find . -type d -name 'docs' -exec rm -rf {} + 2>/dev/null || true \
    && find . -type d -name 'doc' -exec rm -rf {} + 2>/dev/null || true \
    && find . -type f -name '*.pyi' -delete


# ==================== 阶段 4: 最终运行时镜像 ====================
FROM l429609201/su-exec:su-exec

# 环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    MISAKAMF_CONFIG_DIR=/app/config

WORKDIR /app

# 运行时系统依赖 (只装 .so 运行库, 不装 -dev 头文件)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    libpq5 \
    libmariadb3 \
    && addgroup --gid 1000 appgroup \
    && adduser --shell /bin/sh --disabled-password --uid 1000 --gid 1000 appuser \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖 (从编译阶段复制, 无 gcc/dev 残留)
COPY --from=py-builder /install /usr/local/lib/python3.11/site-packages

# 应用代码
COPY src/ ./src/

# 前端构建产物
COPY --from=web-builder /build/dist ./web/dist/

# Go 反代二进制
COPY --from=go-builder /build/mediaflow-proxy ./go-proxy/mediaflow-proxy
RUN chmod +x ./go-proxy/mediaflow-proxy

# 写入构建信息
ARG VERSION=dev
ARG GIT_COMMIT=unknown
ARG BUILD_DATE=unknown
RUN sed -i "s/^BUILD_DATE = .*/BUILD_DATE = \"${BUILD_DATE}\"/" src/version.py \
    && sed -i "s/^GIT_COMMIT = .*/GIT_COMMIT = \"${GIT_COMMIT}\"/" src/version.py \
    && sed -i "s/^VERSION = .*/VERSION = \"${VERSION}\"/" src/version.py

# 入口脚本 + 数据目录
COPY --chmod=755 docker-entrypoint.sh /exec.sh
RUN mkdir -p /app/config/logs /app/config/strm \
    && chown -R appuser:appgroup /app

# 端口
EXPOSE 7789 9906

# OCI 标准标签
LABEL org.opencontainers.image.title="Misaka MediaFlow" \
      org.opencontainers.image.description="115 网盘 + Emby/Jellyfin 媒体服务器管理 — STRM 生成 / 302 反代 / 媒体整理" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.vendor="Misaka Network"

# 健康检查 (用 Python, 不装 curl)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7789/')" || exit 1

CMD ["/exec.sh"]

