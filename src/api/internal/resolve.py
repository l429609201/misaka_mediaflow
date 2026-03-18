# app/api/internal/resolve.py
# 内部 API — Go 反代调用获取直链（含缓存层）

import logging
from fastapi import APIRouter

from src.services.proxy_service import ProxyService
from src.services.link_cache_service import get_cached_url, set_cached_url, make_cache_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Internal"])
_proxy_service = ProxyService()


@router.get("/resolve-link")
async def resolve_link(item_id: str, storage_id: int = 0, api_key: str = "", user_id: str = "", user_agent: str = ""):
    """
    Go 反代调用 — 解析媒体直链

    缓存流程:
      1. 查缓存（内存 → DB）→ 命中直接返回
      2. 未命中 → 调 115 API → 结果写入缓存 → 返回
    """
    # 生成缓存键
    cache_key = make_cache_key(item_id, user_id, api_key)

    # 1. 查缓存
    cached_url = await get_cached_url(cache_key)
    if cached_url:
        logger.info("缓存命中: item_id=%s → 直接返回", item_id)
        return {"url": cached_url, "expires_in": 0, "source": "cache"}

    # 2. 未命中 → 解析
    result = await _proxy_service.resolve_direct_link(item_id, storage_id, api_key, user_id, user_agent)

    # 3. 解析成功 → 写入缓存
    url = result.get("url", "")
    if url:
        expires_in = result.get("expires_in", 0)
        await set_cached_url(
            cache_key=cache_key,
            url=url,
            expires_in=expires_in,
            item_id=item_id,
            storage_id=storage_id,
        )

    return result

