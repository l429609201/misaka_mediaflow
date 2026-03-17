# src/api/internal/redirect_url.py
# 内部 API — Go 反代调用统一 redirect_url 解析（返回 JSON）

import logging
from fastapi import APIRouter
from src.services.redirect_service import RedirectService

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
):
    """
    内部统一解析接口（Go 反代调用，返回 JSON）

    解析优先级:
      1. pickcode / pick_code
      2. url 中提取 pickcode
      3. query.path
      4. url 中提取 path
      5. share_code + receive_code
      6. item_id → PlaybackInfo → Items 明细

    返回:
      - url: 115 直链
      - expires_in: 有效期(秒)
      - source: 解析来源
      - error: 错误信息
    """
    return await _redirect_service.resolve_any(
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
    )

