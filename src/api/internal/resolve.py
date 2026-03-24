# app/api/internal/resolve.py
# 内部 API — Go 反代调用获取直链（含缓存层）

import logging
from fastapi import APIRouter

from src.services.proxy_service import ProxyService
from src.services.link_cache_service import (
    get_cached_url, set_cached_url, make_cache_key, _get_memory_cache,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Internal"])
_proxy_service = ProxyService()


@router.get("/resolve-link")
async def resolve_link(item_id: str, storage_id: int = 0, api_key: str = "", user_id: str = "", user_agent: str = ""):
    """
    Go 反代调用 — 解析媒体直链

    缓存流程（串行，避免重复解析）:
      1. L1 内存查询（同步，~0ms）→ 命中直接返回
      2. L2 DB 缓存查询（~5ms）→ 命中直接返回，顺手回填 L1
      3. L1/L2 均未命中 → 调 MediaItem+115 解析（真正慢的部分，仅执行一次）
      4. 解析成功 → 写入 L1+L2 缓存
    """
    cache_key = make_cache_key(item_id, user_id, api_key)

    # ── Step 1: L1 内存（同步，~0ms）─────────────────────────────────────────
    mem_url = _get_memory_cache().get(cache_key)
    if mem_url:
        logger.info("[resolve] L1命中: item_id=%s → 直接返回", item_id)
        return {"url": mem_url, "expires_in": 0, "source": "cache_l1"}

    # ── Step 2: L2 DB 缓存（~5ms，比 115 API 快 100 倍）─────────────────────
    l2_url = await get_cached_url(cache_key)
    if l2_url:
        logger.info("[resolve] L2命中: item_id=%s → 直接返回", item_id)
        _get_memory_cache().set(cache_key, l2_url)
        return {"url": l2_url, "expires_in": 0, "source": "cache_l2"}

    # ── Step 3: 缓存全未命中 → 真正解析（仅执行一次，彻底避免重复解析）──────
    logger.info("[resolve] 缓存未命中，开始解析: item_id=%s", item_id)
    result = await _proxy_service.resolve_direct_link(item_id, storage_id, api_key, user_id, user_agent)

    if not result.get("url"):
        logger.warning("[resolve] 解析失败: item_id=%s", item_id)
        return {"url": "", "expires_in": 0, "source": "none", "error": "resolve failed"}

    # ── Step 4: 写入缓存 ─────────────────────────────────────────────────────
    url = result["url"]
    expires_in = result.get("expires_in", 0)
    await set_cached_url(
        cache_key=cache_key,
        url=url,
        expires_in=expires_in,
        item_id=item_id,
        storage_id=storage_id,
    )

    return result

