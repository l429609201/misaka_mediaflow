# src/api/internal/emby.py
# 内部 API — Go 反代调用，查询 Emby Item 是否为 STRM 文件

import logging
from fastapi import APIRouter

from src.services.media_server_service import media_server_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Internal-Emby"])


@router.get("/emby/check-strm")
async def check_strm(item_id: str, api_key: str = ""):
    """
    Go 反代调用 — 判断 Emby Item 是否为 STRM 文件。

    使用 media_server_service 获取媒体服务器配置（不再直接读 SystemConfig），
    调用 /emby/Users/{user_id}/Items/{item_id}?Fields=Path 接口查询 Item.Path。

    返回:
        {"is_strm": true/false}
    """
    import httpx

    # 通过统一服务层获取媒体服务器配置
    ms_cfg = await media_server_service.get_config()
    host         = ms_cfg.get("host", "").rstrip("/")
    saved_api_key = ms_cfg.get("api_key", "")
    user_id      = ms_cfg.get("user_id", "")

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
        item_type: str = data.get("Type", "")   # Movie / Episode / Series / ...
        is_strm = path.lower().endswith(".strm")
        logger.info("[check-strm] item_id=%s path=%r is_strm=%s type=%s", item_id, path, is_strm, item_type)
        return {"is_strm": is_strm, "item_type": item_type}

    except Exception as e:
        logger.error("[check-strm] 请求异常: %s", e)
        return {"is_strm": False}

