# 制作 ffmpeg-static 基础镜像

本文档说明如何制作 `l429609201/ffmpeg-static` 镜像，供 Dockerfile 中 `COPY --from` 使用。  
**只需做一次**，之后每次 CI 构建直接从 Docker Hub 拉取，无需任何外部下载。

---

## 第一步：下载 John Van Sickle 静态构建

在**本地（非构建服务器）**下载，下载地址：  
https://johnvansickle.com/ffmpeg/releases/

需要下载的文件：
- `ffmpeg-release-amd64-static.tar.xz`（x86_64）
- `ffmpeg-release-arm64-static.tar.xz`（ARM64，如需多架构）

## 第二步：解压取出二进制

```powershell
# amd64
tar xf ffmpeg-release-amd64-static.tar.xz
# 解压目录类似 ffmpeg-7.0.2-amd64-static/
# 取出 ffmpeg 和 ffprobe 两个文件

# arm64（如需）
tar xf ffmpeg-release-arm64-static.tar.xz
```

## 第三步：整理目录结构

```
ffmpeg-image/
├── Dockerfile
├── amd64/
│   ├── ffmpeg
│   └── ffprobe
└── arm64/
    ├── ffmpeg
    └── ffprobe
```

## 第四步：编写 Dockerfile

```dockerfile
# ffmpeg-image/Dockerfile
# 使用 scratch 基础镜像（零额外体积）
FROM scratch
ARG TARGETARCH
COPY ${TARGETARCH}/ffmpeg  /ffmpeg
COPY ${TARGETARCH}/ffprobe /ffprobe
```

## 第五步：构建多架构镜像并推送

```powershell
cd ffmpeg-image

# 确保 buildx 已启用
docker buildx create --use --name multiarch 2>$null

# 构建 amd64 + arm64 多架构镜像并推送
docker buildx build `
    --platform linux/amd64,linux/arm64 `
    -t l429609201/ffmpeg-static:latest `
    --push `
    .
```

推送完成后即可在 Dockerfile 中使用：
```dockerfile
FROM --platform=$TARGETPLATFORM l429609201/ffmpeg-static:latest AS ffmpeg-fetcher
```

---

## 更新镜像（ffmpeg 升级时）

重复第一步到第五步即可，Docker Hub 会覆盖 latest tag。  
Dockerfile 无需任何修改，下次 CI 构建自动使用新版本。

