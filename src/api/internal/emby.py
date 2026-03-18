# src/api/internal/emby.py
# 内部 API — Go 反代调用，查询 Emby Item 是否为 STRM 文件

import logging
from fastapi import APIRouter
from sqlalchemy import select

from src.db import get_async_session_local
from src.db.models import SystemConfig

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Internal-Emby"])


@router.get("/emby/check-strm")
async def check_strm(item_id: str, api_key: str = ""):
    """
    Go 反代调用 — 判断 Emby Item 是否为 STRM 文件。

    使用数据库中保存的 media_server_host / media_server_user_id / media_server_api_key，
    调用 /emby/Users/{user_id}/Items/{item_id}?Fields=Path 接口查询 Item.Path。

    返回:
        {"is_strm": true/false}
    """
    import httpx

    # 从数据库读取媒体服务器配置
    async with get_async_session_local() as db:
        keys_needed = ["media_server_host", "media_server_api_key", "media_server_user_id"]
        cfg = {}
        for k in keys_needed:
            row = await db.execute(select(SystemConfig).where(SystemConfig.key == k))
            item = row.scalars().first()
            cfg[k] = item.value if item else ""

    host = cfg.get("media_server_host", "").rstrip("/")
    saved_api_key = cfg.get("media_server_api_key", "")
    user_id = cfg.get("media_server_user_id", "")

    # api_key 优先用请求传入的（Go 从 PlaybackInfo 请求里提取），其次用数据库保存的
    effective_api_key = api_key or saved_api_key

    if not host or not user_id or not effective_api_key:
        logger.warning(
            "[check-strm] 配置不完整: host=%r user_id=%r api_key有值=%s",
            host, user_id, bool(effective_api_key),
        )
        return {"is_strm": False}

    url = f"{host}/emby/Users/{user_id}/Items/{item_id}?Fields=Path&api_key={effective_api_key}"
    logger.info("[check-strm] 查询 item_id=%s url=%s", item_id, url)

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            logger.warning("[check-strm] Emby 返回 status=%d item_id=%s", resp.status_code, item_id)
            return {"is_strm": False}

        data = resp.json()
        path: str = data.get("Path", "")
        is_strm = path.lower().endswith(".strm")
        logger.info("[check-strm] item_id=%s path=%r is_strm=%s", item_id, path, is_strm)
        return {"is_strm": is_strm}

    except Exception as e:
        logger.error("[check-strm] 请求异常: %s", e)
        return {"is_strm": False}

