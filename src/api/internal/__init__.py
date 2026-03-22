# app/api/internal/__init__.py
# 内部 API（仅 Go 反代服务调用）

from fastapi import APIRouter

from src.api.internal.resolve import router as resolve_router
from src.api.internal.p115 import router as p115_router
from src.api.internal.redirect_url import router as redirect_url_router
from src.api.internal.emby import router as emby_router
from src.api.internal.subtitle import router as subtitle_router
from src.services.link_cache_service import get_cache_stats, cleanup_expired

internal_router = APIRouter(prefix="/internal")
internal_router.include_router(resolve_router)
internal_router.include_router(p115_router)
internal_router.include_router(redirect_url_router)
internal_router.include_router(emby_router)
internal_router.include_router(subtitle_router)


@internal_router.get("/cache/stats")
async def cache_stats():
    """缓存统计（Go 可转发到此接口）"""
    return get_cache_stats()


@internal_router.post("/cache/cleanup")
async def cache_cleanup():
    """清理过期缓存条目"""
    await cleanup_expired()
    return {"status": "ok"}


__all__ = ["internal_router"]

