# Misaka MediaFlow

302 反向代理 & STRM 生成服务 — 适用于 Emby / Jellyfin 媒体服务器。

## ✨ 功能特性

- **302 反代** — Go (Gin) 高性能反代，拦截视频流请求返回 302 直链
- **STRM 生成** — 自动生成 `.strm` 文件，支持多种模式
- **115 网盘** — 一等公民支持，Cookie 直链 + OpenAPI 网盘整理
- **多存储适配** — CloudDrive2 / Alist / 115 直连
- **双层缓存** — 内存 L1 + Redis L2
- **管理后台** — React + Ant Design 可视化管理

## 🏗️ 架构

```
客户端 → Go 反代 (8888) → 302 重定向到 CDN 直链
                       ↘ 透传到 Emby/Jellyfin
         Python 管理服务 (9000) — API / STRM / 115 模块
         PostgreSQL / MySQL — 数据持久化
         Redis — 共享缓存
```

## 🚀 快速开始

### Docker Compose（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/your-org/mediaflow.git
cd mediaflow

# 2. 复制配置
cp config/config.yaml.example config/config.yaml
# 编辑 config/config.yaml 填写 Emby 地址和 API Key

# 3. 启动
docker-compose up -d

# 4. 访问
# 管理后台: http://localhost:9000/docs
# 反代入口: http://localhost:8888
```

### 环境变量

所有配置均可通过 `MISAKAMF_` 前缀环境变量覆盖：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MISAKAMF_TZ` | 时区 | `Asia/Shanghai` |
| `MISAKAMF_DATABASE_TYPE` | 数据库类型 | `postgresql` |
| `MISAKAMF_DATABASE_HOST` | 数据库地址 | `127.0.0.1` |
| `MISAKAMF_DATABASE_PASSWORD` | 数据库密码 | — |
| `MISAKAMF_REDIS_HOST` | Redis 地址 | `127.0.0.1` |
| `MISAKAMF_MEDIA_SERVER_HOST` | Emby/Jellyfin 地址 | — |
| `MISAKAMF_MEDIA_SERVER_API_KEY` | API Key | — |
| `MISAKAMF_P115_ENABLED` | 启用 115 | `false` |
| `MISAKAMF_P115_COOKIE` | 115 Cookie | — |

## 📁 项目结构

```
mediaflow/
├── go-proxy/              # Go 反代服务 (302)
│   ├── cmd/proxy/         # 入口
│   └── internal/          # 配置/缓存/中间件/处理器/路由
├── py-server/             # Python 管理服务
│   ├── app/               # FastAPI 应用
│   │   ├── version.py     # 版本号硬编码
│   │   ├── core/          # 配置/时区/安全
│   │   ├── db/            # ORM 模型 (11 张表)
│   │   ├── adapters/      # 存储/媒体服务器适配器
│   │   ├── services/      # 业务逻辑
│   │   ├── api/           # REST API
│   │   └── schemas/       # Pydantic 模型
│   └── alembic/           # 数据库迁移
├── config/                # 配置文件
├── docker-compose.yml     # 编排
└── docs/                  # 设计文档
```

## 🛠️ 技术栈

| 层次 | 技术 |
|------|------|
| Go 反代 | Go 1.22 + Gin + gorilla/websocket |
| Python 管理 | FastAPI + SQLAlchemy 2.0 + Alembic |
| 数据库 | PostgreSQL 16+ / MySQL 8.0+ |
| 缓存 | Redis 7+ (L2) + 内存 LRU (L1) |
| 前端 | React 18 + Ant Design 5 + Tailwind CSS 4 |

## 📄 许可证

MIT License

