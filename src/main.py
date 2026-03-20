# src/main.py — 对齐 misaka_danmu_server 的 src/main.py

import logging
import os
from pathlib import Path

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.version import APP_NAME, VERSION
from src.core.config import settings
from src.core.security import initialize_admin_password
from src.core.scheduler import start_scheduler, shutdown_scheduler
from src.services import setup_logging
from src.services import go_proxy_service

logger = logging.getLogger(__name__)


# ==================== Banner ====================
def _print_banner():
    from src.core.timezone import tm
    db = settings.database
    rd = settings.redis
    sep = "=" * 55

    # Database URL（密码隐藏）
    db_url = f"{db.type}://{db.user}:***@{db.host}:{db.port}/{db.name}" if db.password else \
             f"{db.type}://{db.host}:{db.port}/{db.name}"

    # Cache 显示
    if rd.enabled:
        if rd.password:
            cache_str = f"redis://***@{rd.host}:{rd.port}/{rd.db}"
        else:
            cache_str = f"redis://{rd.host}:{rd.port}/{rd.db}"
    else:
        cache_str = "memory"

    banner = (
        f"\n{sep}\n"
        f"  {APP_NAME} v{VERSION}\n"
        f"  Timezone : {tm.tz_offset_str}\n"
        f"  Port     : {settings.server.port}\n"
        f"  Database : {db_url}\n"
        f"  Cache    : {cache_str}\n"
        f"  Log Level: {settings.server.log_level}\n"
        f"{sep}"
    )
    logger.info(banner)


# ==================== Lifespan（对齐弹幕库） ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — 对齐弹幕库的 lifespan 模式"""
    from src.db import init_db_tables, close_db_engine, DatabaseStartupError

    # ★ 日志系统初始化（对齐弹幕库：在 lifespan 中调用，独立模块管理）
    setup_logging()

    _print_banner()

    # 1. 数据库初始化（自动建库 + 建表 + schema 迁移）
    try:
        await init_db_tables(app)
    except DatabaseStartupError:
        logger.critical("启动失败：数据库初始化错误，进程退出")
        os._exit(1)

    # 2. Redis 连通性检查
    if settings.redis.enabled:
        logger.info("检查 Redis 连接...")
        try:
            import redis as redis_lib
            r = redis_lib.Redis(
                host=settings.redis.host,
                port=settings.redis.port,
                db=settings.redis.db,
                password=settings.redis.password or None,
                socket_connect_timeout=5,
            )
            r.ping()
            r.close()
            logger.info(f"Redis 连接成功: {settings.redis.host}:{settings.redis.port}")
        except Exception as e:
            logger.error(f"Redis 连接失败: {e}")
            logger.critical("启动失败：Redis 不可达，请修复 Redis 或将 redis.enabled 设为 false")
            os._exit(1)
    else:
        logger.info("Redis 未启用，使用内存缓存")

    # 3. 初始化管理员密码
    initialize_admin_password()

    # 4. 从数据库加载 HTTP 代理配置，注入 core 层
    from src.services.proxy_config_service import init_proxy_config
    await init_proxy_config()

    # 4.5 预热 P115Client（提前完成 RSA 初始化，消除首播冷启动延迟）
    from src.services.p115_warmup_service import warmup_p115_client
    await warmup_p115_client()

    # 5. 启动定时调度器
    start_scheduler()

    # 6. Go 反代随主程序自动启动
    go_result = await go_proxy_service.start()
    if go_result.get("success"):
        logger.info("Go 反代自动启动成功: pid=%s port=%s", go_result.get("pid"), go_result.get("port"))
    else:
        logger.warning("Go 反代自动启动跳过: %s", go_result.get("message", ""))

    logger.info(f"{APP_NAME} 已启动 — 监听 {settings.server.host}:{settings.server.port}")
    yield

    # 关闭
    await go_proxy_service.stop()
    shutdown_scheduler()
    await close_db_engine(app)
    logger.info(f"{APP_NAME} 已停止")


# ==================== FastAPI instance ====================
app = FastAPI(
    title=APP_NAME,
    version=VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
from src.api.v1 import v1_router                   # noqa: E402
from src.api.internal import internal_router        # noqa: E402
from src.api.redirect_url import router as redirect_url_router  # noqa: E402
 
app.include_router(v1_router)
app.include_router(internal_router)
# ⭐ redirect_url 同时挂根路径，STRM 可直接写 http://host/redirect_url?pickcode=xxx
app.include_router(redirect_url_router)

# Static files (production build)
_web_dist = Path(__file__).parent.parent / "web" / "dist"
_web_index = _web_dist / "index.html"
_web_assets = _web_dist / "assets"
if _web_assets.exists():
    app.mount("/web/assets", StaticFiles(directory=str(_web_assets)), name="web-assets")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/web/login", status_code=302)


@app.get("/web", include_in_schema=False)
async def web_root():
    return RedirectResponse(url="/web/login", status_code=302)


@app.get("/web/{path:path}", include_in_schema=False)
async def web_spa(path: str):
    if not _web_dist.exists() or not _web_index.exists():
        return {"detail": "Web frontend not built"}

    requested = (_web_dist / path).resolve()
    try:
        requested.relative_to(_web_dist.resolve())
    except ValueError:
        return {"detail": "Not Found"}

    if requested.is_file():
        return FileResponse(str(requested))

    return FileResponse(str(_web_index))


# ==================== 直接运行入口（对齐弹幕库 python -m src.main） ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=True,
        reload_excludes=["config/logs/*", "*.log"],
        log_level=settings.server.log_level,
    )

