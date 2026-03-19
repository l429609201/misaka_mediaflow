# app/api/v1/__init__.py
# v1 API 路由汇总

from fastapi import APIRouter

from src.api.v1.auth import router as auth_router
from src.api.v1.storage import router as storage_router
from src.api.v1.strm import router as strm_router
from src.api.v1.p115 import router as p115_router
from src.api.v1.system import router as system_router
from src.api.v1.proxy_settings import router as proxy_settings_router
from src.api.redirect_url import router as redirect_url_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth_router)
v1_router.include_router(storage_router)
v1_router.include_router(strm_router)
v1_router.include_router(p115_router)
v1_router.include_router(system_router)
v1_router.include_router(proxy_settings_router)

# ⭐ 统一 redirect_url 挂在 /api/v1 下，对齐 P115StrmHelper 协议风格
v1_router.include_router(redirect_url_router)

__all__ = ["v1_router"]

