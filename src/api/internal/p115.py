# app/api/internal/p115.py
# 内部 API — Go 反代调用获取 115 直链（含缓存层）

import json as _json
import logging
from fastapi import APIRouter, Query
from sqlalchemy import select

from src.db import get_async_session_local
from src.db.models import SystemConfig
from src.services.link_cache_service import get_cached_url, set_cached_url, make_cache_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/p115", tags=["Internal-115"])


def _get_manager():
    """延迟导入避免循环依赖"""
    from src.adapters.storage.p115 import P115Manager
    return P115Manager()


@router.get("/download-url")
async def get_download_url(pick_code: str, user_agent: str = Query("")):
    """
    Go /p115/play/:pickCode 路由回调 — 通过 pick_code 获取 115 CDN 直链

    缓存流程:
      1. 查缓存（内存 → DB）→ 命中直接返回
      2. 未命中 → 调 115 API → 结果写入缓存 → 返回
    """
    # 生成缓存键（含 UA 分类，不同客户端可能需要不同直链）
    cache_key = make_cache_key("p115", pick_code, user_agent or "default")

    # 1. 查缓存
    cached_url = await get_cached_url(cache_key)
    if cached_url:
        logger.info("[115] 缓存命中: pick_code=%s → 直接返回", pick_code)
        return {"url": cached_url, "expires_in": 0, "file_name": "", "source": "cache"}

    # 2. 未命中 → 调 115 API
    manager = _get_manager()

    if not manager.enabled:
        logger.warning("115 模块未启用，无法获取直链: pick_code=%s", pick_code)
        return {"url": "", "expires_in": 0, "file_name": "", "error": "115 module not enabled"}

    if not manager.auth.has_cookie:
        logger.warning("115 Cookie 未配置，无法获取直链: pick_code=%s", pick_code)
        return {"url": "", "expires_in": 0, "file_name": "", "error": "115 cookie not set"}

    try:
        direct_link = await manager.adapter.get_direct_link(
            cloud_path="",
            pick_code=pick_code,
        )

        if not direct_link.url:
            return {"url": "", "expires_in": 0, "file_name": "", "error": "empty download url"}

        # 3. 写入缓存
        await set_cached_url(
            cache_key=cache_key,
            url=direct_link.url,
            expires_in=direct_link.expires_in,
            item_id=pick_code,
        )

        logger.info("115 直链获取成功: pick_code=%s, file=%s", pick_code, direct_link.file_name)
        return {
            "url": direct_link.url,
            "expires_in": direct_link.expires_in,
            "file_name": direct_link.file_name,
            "source": "api",
        }
    except Exception as e:
        logger.error("115 直链获取失败: pick_code=%s, error=%s", pick_code, str(e))
        return {"url": "", "expires_in": 0, "file_name": "", "error": str(e)}


@router.get("/api-interval")
async def get_api_interval():
    """Go 反代调用 — 获取 115 API 请求间隔（秒），用于 seek 防抖"""
    try:
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == "p115_settings")
            )
            cfg = result.scalars().first()
            if cfg and cfg.value:
                data = _json.loads(cfg.value)
                return {"api_interval": data.get("api_interval", 1.0)}
    except Exception:
        pass
    return {"api_interval": 1.0}

