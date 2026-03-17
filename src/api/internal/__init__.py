# app/api/internal/__init__.py
# 内部 API（仅 Go 反代服务调用）

from fastapi import APIRouter

from src.api.internal.resolve import router as resolve_router
from src.api.internal.p115 import router as p115_router
from src.api.internal.redirect_url import router as redirect_url_router

internal_router = APIRouter(prefix="/internal")
internal_router.include_router(resolve_router)
internal_router.include_router(p115_router)
internal_router.include_router(redirect_url_router)

__all__ = ["internal_router"]

