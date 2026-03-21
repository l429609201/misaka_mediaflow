# app/api/internal/resolve.py
# 内部 API — Go 反代调用获取直链（含缓存层）

import asyncio
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

    缓存流程（并行优化）:
      1. L1 内存查询（同步，~0ms）→ 命中直接返回
      2. L1 未命中 → 并行发起：L2 DB缓存查询 + MediaItem+115解析
         - 谁先返回有效 URL 就用谁，另一个结果丢弃
      3. 解析成功 → 写入缓存
    """
    cache_key = make_cache_key(item_id, user_id, api_key)

    # ── Step 1: L1 内存（同步，~0ms，命中直接返回无需并行）──────────────────
    mem_url = _get_memory_cache().get(cache_key)
    if mem_url:
        logger.info("[resolve] L1命中: item_id=%s → 直接返回", item_id)
        return {"url": mem_url, "expires_in": 0, "source": "cache_l1"}

    # ── Step 2: L1 未命中 → 并行：L2 DB缓存 + MediaItem解析 ─────────────────
    # 两个协程同时发起，谁先拿到有效 URL 就用谁
    async def _l2_lookup() -> dict | None:
        url = await get_cached_url(cache_key)
        if url:
            return {"url": url, "expires_in": 0, "source": "cache_l2"}
        return None

    async def _resolve() -> dict | None:
        r = await _proxy_service.resolve_direct_link(item_id, storage_id, api_key, user_id, user_agent)
        if r.get("url"):
            return r
        return None

    l2_task = asyncio.ensure_future(_l2_lookup())
    resolve_task = asyncio.ensure_future(_resolve())

    result = None
    try:
        # 等待两个任务都完成，优先用 L2 缓存结果
        done, pending = await asyncio.wait(
            [l2_task, resolve_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        # 检查先完成的任务
        for task in done:
            r = task.result()
            if r and r.get("url"):
                result = r
                # 取消另一个任务（如果是 L2 命中，不需要再等解析）
                for t in pending:
                    t.cancel()
                break

        # 先完成的没有结果，等剩余的
        if result is None and pending:
            for task in pending:
                try:
                    r = await task
                    if r and r.get("url") and result is None:
                        result = r
                except asyncio.CancelledError:
                    pass
    except Exception as e:
        logger.warning("[resolve] 并行查询异常: %s item_id=%s", e, item_id)
        # 降级：等两个任务都结束，取第一个有效结果
        for task in [l2_task, resolve_task]:
            try:
                r = await task
                if r and r.get("url") and result is None:
                    result = r
            except Exception:
                pass

    if result is None:
        result = {"url": "", "expires_in": 0, "source": "none", "error": "resolve failed"}

    # ── Step 3: 解析成功 → 写入缓存（L2 命中的不重复写）───────────────────
    url = result.get("url", "")
    if url and result.get("source", "") not in ("cache_l1", "cache_l2"):
        expires_in = result.get("expires_in", 0)
        await set_cached_url(
            cache_key=cache_key,
            url=url,
            expires_in=expires_in,
            item_id=item_id,
            storage_id=storage_id,
        )
    elif url and result.get("source") == "cache_l2":
        logger.info("[resolve] L2命中: item_id=%s → 直接返回", item_id)

    return result

