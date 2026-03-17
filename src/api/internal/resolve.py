# app/api/internal/resolve.py
# 内部 API — Go 缓存未命中时调用获取直链

import logging
from fastapi import APIRouter

from src.services.proxy_service import ProxyService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Internal"])
_proxy_service = ProxyService()


@router.get("/resolve-link")
async def resolve_link(item_id: str, storage_id: int = 0, api_key: str = "", user_id: str = ""):
    """
    Go 反代缓存未命中时调用
    参数:
      - item_id:    Emby/Jellyfin 媒体 ID
      - storage_id: 存储源 ID
      - api_key:    Emby API Key
      - user_id:    Emby UserId（调 Items API 必需，Go 从请求 query 中提取并透传）
    返回:
      - url: 302 直链
      - expires_in: 有效期(秒)
    """
    return await _proxy_service.resolve_direct_link(item_id, storage_id, api_key, user_id)

