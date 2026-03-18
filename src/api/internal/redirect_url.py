# src/api/internal/redirect_url.py
# 内部 API — Go 反代调用统一 redirect_url 解析（含缓存层）

import logging
from fastapi import APIRouter
from src.services.redirect_service import RedirectService
from src.services.link_cache_service import get_cached_url, set_cached_url, make_cache_key

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Internal-Redirect"])

_redirect_service = RedirectService()


@router.get("/redirect_url/resolve")
async def resolve_redirect_url(
    pickcode: str = "",
    pick_code: str = "",
    path: str = "",
    url: str = "",
    file_name: str = "",
    share_code: str = "",
    receive_code: str = "",
    item_id: str = "",
    storage_id: int = 0,
    api_key: str = "",
    user_agent: str = "",
):
    """
    内部统一解析接口（Go 反代调用，含缓存层）

    缓存流程:
      1. 查缓存（内存 → DB）→ 命中直接返回
      2. 未命中 → 解析 → 结果写入缓存 → 返回
    """
    # 确定缓存键的主标识
    pc = pickcode or pick_code
    if pc:
        cache_key = make_cache_key("redirect", pc, user_agent or "default")
    elif path:
        cache_key = make_cache_key("redirect_path", path)
    elif item_id:
        cache_key = make_cache_key("redirect_item", item_id, api_key)
    else:
        cache_key = ""

    # 1. 查缓存
    if cache_key:
        cached_url = await get_cached_url(cache_key)
        if cached_url:
            logger.info("缓存命中: %s → 直接返回", pc or path or item_id)
            return {"url": cached_url, "expires_in": 0, "source": "cache"}

    # 2. 未命中 → 解析
    result = await _redirect_service.resolve_any(
        pickcode=pickcode,
        pick_code=pick_code,
        path=path,
        url=url,
        file_name=file_name,
        share_code=share_code,
        receive_code=receive_code,
        item_id=item_id,
        storage_id=storage_id,
        api_key=api_key,
        user_agent=user_agent,
    )

    # 3. 解析成功 → 写入缓存
    resolved_url = result.get("url", "") if isinstance(result, dict) else ""
    if cache_key and resolved_url:
        expires_in = result.get("expires_in", 0) if isinstance(result, dict) else 0
        await set_cached_url(
            cache_key=cache_key,
            url=resolved_url,
            expires_in=expires_in,
            item_id=item_id or pc or "",
            storage_id=storage_id,
        )

    return result

