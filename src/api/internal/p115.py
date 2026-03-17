# app/api/internal/p115.py
# 内部 API — Go 反代调用获取 115 直链（/p115/play 路由回调）

import json as _json
import logging
from fastapi import APIRouter
from sqlalchemy import select

from src.db import get_async_session_local
from src.db.models import SystemConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/p115", tags=["Internal-115"])


def _get_manager():
    """延迟导入避免循环依赖"""
    from src.adapters.storage.p115 import P115Manager
    return P115Manager()


@router.get("/download-url")
async def get_download_url(pick_code: str):
    """
    Go /p115/play/:pickCode 路由回调 — 通过 pick_code 获取 115 CDN 直链

    参数:
      - pick_code: 115 文件提取码

    返回:
      - url: 115 CDN 直链
      - expires_in: 有效期(秒)
      - file_name: 文件名
      - error: 错误信息(可选)
    """
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

        logger.info("115 直链获取成功: pick_code=%s, file=%s", pick_code, direct_link.file_name)
        return {
            "url": direct_link.url,
            "expires_in": direct_link.expires_in,
            "file_name": direct_link.file_name,
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

