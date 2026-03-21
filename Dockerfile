# =============================================================
# Misaka MediaFlow — 五阶段 Docker 构建
#
#   1. Node      → 编译前端 (React + Vite)  [$BUILDPLATFORM 原生编译]
#   2. Go        → 编译反代 (Gin, CGO=0 静态链接)
#   3. ffmpeg    → 最小化静态 ffmpeg/ffprobe
#                  只编译字幕提取所需模块，体积 ~8MB（vs apt 的 ~350MB）
#                  支持格式: MKV/MP4/MOV 封装 + ASS/SRT/SRT/PGS/VOBSUB 字幕
#   4. Python    → 编译 C 扩展 (build-essential + dev headers)
#   5. Runtime   → 纯运行时 (无编译器, su-exec 降权)
#
# 基底: l429609201/su-exec:3.12 (Debian slim + Python 3.12 + su-exec)
# 安全: su-exec 降权至 UID=1000 非 root 用户
# 体积: ~220MB (含最小化 ffmpeg ~8MB)
# =============================================================

ARG GO_VERSION=1.22
ARG BUILD_DATE
ARG VERSION=dev
ARG FFMPEG_VERSION=7.1

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


# ==================== 阶段 3: 最小化 ffmpeg 静态编译 ====================
# 目标：只编译字幕提取所需的最小模块集，静态链接，无运行时依赖
#
# 启用的封装格式 demuxer（读取容器）:
#   matroska  — MKV / MKA（最常见内封字幕载体）
#   mov,mp4   — MP4 / MOV / M4V（也可能内封字幕）
#
# 启用的字幕 decoder（文本字幕，可提取为 ASS/SRT）:
#   ass / ssa          — ASS/SSA 软字幕（最常见）
#   subrip / srt       — SRT 软字幕
#   webvtt             — WebVTT 字幕
#   mov_text           — MP4 内嵌文本字幕（tx3g）
#   hdmv_pgs_subtitle  — PGS 蓝光图形字幕（ffprobe 探测用，提取为 sup）
#   dvd_subtitle       — VOBSUB DVD 图形字幕（ffprobe 探测用，提取为 sub/idx）
#
# 启用的 muxer（输出格式）:
#   ass / srt / webvtt / sup / matroska
#
# 启用的 protocol（网络访问）:
#   http / https / tcp / file / pipe
#
# 完全禁用: 所有视频/音频 codec、硬件加速、滤镜、文档、示例
FROM debian:bookworm-slim AS ffmpeg-builder

ARG FFMPEG_VERSION
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    # 编译工具
    build-essential \
    pkg-config \
    nasm \
    # ffmpeg 依赖（最小集）
    zlib1g-dev \
    wget \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 下载 ffmpeg 源码
RUN wget -q "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" \
    && tar xf "ffmpeg-${FFMPEG_VERSION}.tar.xz" \
    && rm "ffmpeg-${FFMPEG_VERSION}.tar.xz"

RUN cd "ffmpeg-${FFMPEG_VERSION}" && ./configure \
    # 静态链接，输出独立二进制，无 .so 运行时依赖
    --enable-static \
    --disable-shared \
    --prefix=/ffmpeg-out \
    # 禁用所有模块，然后只开启需要的
    --disable-everything \
    --disable-doc \
    --disable-debug \
    --disable-htmlpages \
    --disable-manpages \
    --disable-podpages \
    --disable-txtpages \
    --disable-avdevice \
    --disable-postproc \
    --disable-network \
    # 重新启用 network（http/https 拉取 CDN 直链需要）
    --enable-network \
    # ── 封装格式 demuxer（读取容器）──────────────────────────
    --enable-demuxer=matroska \
    --enable-demuxer=mov \
    --enable-demuxer=mp4 \
    --enable-demuxer=avi \
    # ── 字幕 codec ────────────────────────────────────────────
    --enable-decoder=ass \
    --enable-decoder=ssa \
    --enable-decoder=subrip \
    --enable-decoder=srt \
    --enable-decoder=webvtt \
    --enable-decoder=mov_text \
    --enable-decoder=hdmv_pgs_subtitle \
    --enable-decoder=dvd_subtitle \
    --enable-decoder=dvbsub \
    --enable-encoder=ass \
    --enable-encoder=subrip \
    --enable-encoder=webvtt \
    --enable-muxer=ass \
    --enable-muxer=srt \
    --enable-muxer=webvtt \
    --enable-muxer=matroska \
    --enable-muxer=sup \
    # ── 网络协议 ──────────────────────────────────────────────
    --enable-protocol=http \
    --enable-protocol=https \
    --enable-protocol=tcp \
    --enable-protocol=file \
    --enable-protocol=pipe \
    # ── 优化体积 ──────────────────────────────────────────────
    --enable-small \
    --extra-cflags="-Os -ffunction-sections -fdata-sections" \
    --extra-ldflags="-Wl,--gc-sections" \
    && make -j$(nproc) \
    && make install \
    # 只保留 ffmpeg + ffprobe 两个二进制
    && strip /ffmpeg-out/bin/ffmpeg /ffmpeg-out/bin/ffprobe


# ==================== 阶段 4: Python 依赖编译 ====================
FROM l429609201/su-exec:3.12 AS py-builder

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
RUN pip install --no-cache-dir --no-compile -r requirements.txt --target .

# 清理：删除测试/文档/类型桩/缓存，压缩体积
RUN find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null; \
    find . -type f -name '*.pyc' -delete 2>/dev/null; \
    find . -type f -name '*.pyo' -delete 2>/dev/null; \
    find . -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null; \
    find . -type d -name 'tests' -exec rm -rf {} + 2>/dev/null; \
    find . -type d -name 'test' -exec rm -rf {} + 2>/dev/null; \
    find . -type d -name 'docs' -exec rm -rf {} + 2>/dev/null; \
    find . -type d -name 'doc' -exec rm -rf {} + 2>/dev/null; \
    find . -type f -name '*.pyi' -delete 2>/dev/null; \
    true


# ==================== 阶段 5: 最终运行时镜像 ====================
FROM l429609201/su-exec:3.12

# 环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    MISAKAMF_CONFIG_DIR=/app/config

WORKDIR /app

# 运行时系统依赖 (只装 .so 运行库, 不装 -dev 头文件)
# ffmpeg 已通过静态编译独立引入，此处无需安装
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    libpq5 \
    libmariadb3 \
    && addgroup --gid 1000 mediaflow \
    && adduser --shell /bin/sh --disabled-password --uid 1000 --gid 1000 mediaflow \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖 (从编译阶段复制, 无 gcc/dev 残留)
COPY --from=py-builder /install /usr/local/lib/python3.12/site-packages

# 验证关键依赖能正常 import（构建时就发现问题，而不是运行时才报错）
RUN python -c "import uvicorn; import fastapi; import p115client; print('All imports OK')"

# 最小化静态 ffmpeg/ffprobe（仅含字幕提取所需模块，约 8MB）
COPY --from=ffmpeg-builder /ffmpeg-out/bin/ffmpeg  /usr/local/bin/ffmpeg
COPY --from=ffmpeg-builder /ffmpeg-out/bin/ffprobe /usr/local/bin/ffprobe
RUN chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
    # 验证二进制可用，并输出支持的格式确认（构建时可见）
    && ffmpeg -version 2>&1 | head -3 \
    && ffprobe -version 2>&1 | head -1

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
    && chown -R mediaflow:mediaflow /app

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
