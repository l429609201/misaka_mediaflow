# app/api/internal/resolve.py
# 内部 API — Go 缓存未命中时调用获取直链

import logging
from fastapi import APIRouter

from src.services.proxy_service import ProxyService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Internal"])
_proxy_service = ProxyService()


@router.get("/resolve-link")
async def resolve_link(item_id: str, storage_id: int = 0, api_key: str = "", user_id: str = "", user_agent: str = ""):
    """
    Go 反代缓存未命中时调用
    参数:
      - item_id:    Emby/Jellyfin 媒体 ID
      - storage_id: 存储源 ID
      - api_key:    Emby API Key
      - user_id:    Emby UserId
      - user_agent: 播放器真实 UA（透传给 115 downurl 接口）
    """
    return await _proxy_service.resolve_direct_link(item_id, storage_id, api_key, user_id, user_agent)

