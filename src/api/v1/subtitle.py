# src/api/v1/subtitle.py
# 字幕管理 API — 供前端展示内封字幕缓存和字体状态

import asyncio
import logging
import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.core.security import verify_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/subtitle", tags=["字幕管理"])


# ==================== 内封字幕缓存列表 ====================

@router.get("/embedded/list", dependencies=[Depends(verify_token)])
async def list_embedded_subtitle_cache():
    """
    返回所有已缓存的内封字幕列表。
    包含 item_id、lang、title、codec、size、剩余有效期(秒)。
    """
    from src.services.subtitle_service import _sub_cache, _sub_cache_info

    now = time.monotonic()
    items = []
    for item_id, (data, expire_ts) in list(_sub_cache.items()):
        if expire_ts < now:
            continue
        info = _sub_cache_info.get(item_id, {})
        items.append({
            "item_id": item_id,
            "lang": info.get("lang", ""),
            "title": info.get("title", ""),
            "codec": info.get("codec", ""),
            "size": len(data),
            "ttl": max(0, int(expire_ts - now)),
        })

    # 按剩余时间降序
    items.sort(key=lambda x: x["ttl"], reverse=True)
    return {"total": len(items), "items": items}


# ==================== 字体状态 ====================

@router.get("/font/status", dependencies=[Depends(verify_token)])
async def get_font_status():
    """
    返回字体目录当前状态。
    包括：字体目录路径、DB 中已索引字体文件数量、face 总数、字体列表（前200条）。
    """
    import json as _json
    from sqlalchemy import select, func
    from src.services.font_index_service import _FONTS_ROOT, _FONTS_DOWNLOAD, _last_sync_at
    from src.db import get_async_session_local
    from src.db.models import FontFile, FontFace

    result = {
        "fonts_root": str(_FONTS_ROOT),
        "downloads_dir": str(_FONTS_DOWNLOAD),
        "last_sync_at": _last_sync_at if _last_sync_at > 0 else None,
        "file_count": 0,
        "face_count": 0,
        "fonts": [],
    }

    try:
        async with get_async_session_local() as db:
            result["file_count"] = (
                await db.execute(select(func.count()).select_from(FontFile))
            ).scalar() or 0

            result["face_count"] = (
                await db.execute(select(func.count()).select_from(FontFace))
            ).scalar() or 0

            # 字体列表（join，前200条，按路径+face_index排序）
            stmt = (
                select(
                    FontFile.path, FontFile.file_size,
                    FontFace.face_index, FontFace.family_names, FontFace.full_names,
                    FontFace.weight, FontFace.is_bold, FontFace.is_italic, FontFace.scanned_at,
                )
                .join(FontFace, FontFace.file_id == FontFile.id)
                .order_by(FontFile.path, FontFace.face_index)
                .limit(200)
            )
            fonts = []
            for r in (await db.execute(stmt)).fetchall():
                try:
                    family = _json.loads(r.family_names) if r.family_names else []
                except Exception:
                    family = []
                try:
                    full = _json.loads(r.full_names) if r.full_names else []
                except Exception:
                    full = []
                fonts.append({
                    "path": r.path,
                    "file_size": r.file_size,
                    "face_index": r.face_index,
                    "family_names": family,
                    "full_names": full,
                    "weight": r.weight,
                    "is_bold": bool(r.is_bold),
                    "is_italic": bool(r.is_italic),
                    "scanned_at": r.scanned_at,
                })
            result["fonts"] = fonts
    except Exception as e:
        logger.warning("[subtitle-api] 获取字体状态失败: %s", e)
        result["error"] = str(e)

    return result


# ==================== 手动触发字体扫描 ====================

@router.post("/font/scan", dependencies=[Depends(verify_token)])
async def trigger_font_scan():
    """手动触发字体目录扫描（force=True 忽略间隔限制）。"""
    from src.services.font_index_service import scan_and_sync
    try:
        stat = await scan_and_sync(force=True)
        return {"success": True, **stat}
    except Exception as e:
        logger.warning("[subtitle-api] 字体扫描触发失败: %s", e)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

