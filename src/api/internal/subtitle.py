# src/api/internal/subtitle.py
# 内部字幕 API — 供 Go 反代调用
#
# 路由：
#   GET  /internal/subtitle/proxy   - 字幕透传/fontInAss 转发（Go 截到字幕请求时调用）
#   POST /internal/subtitle/trigger - 302 成功后触发内封字幕提取
#   GET  /internal/subtitle/embedded/{item_id} - 查询并返回已缓存的内封字幕
#   GET  /internal/subtitle/config  - 返回当前字幕功能配置（供 Go 判断是否需要拦截）

import logging
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from src.services.subtitle_service import (
    proxy_to_font_in_ass,
    get_cached_embedded_sub,
    trigger_embedded_sub_extraction,
    _load_config,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Internal-Subtitle"])


@router.get("/subtitle/proxy")
async def subtitle_proxy(request: Request):
    """
    字幕透传/fontInAss 转发。

    Go 反代拦截到 /emby/videos/:id/Subtitles/:subId/Stream.ass 等请求后，
    调用此接口。Python 决定是转发给 fontInAss 还是直接让 Go 透传 Emby。

    处理优先级：
      1. 检查内封字幕缓存（embedded_sub），命中则直接返回缓存内容送给 fontInAss 处理
      2. 转发给 fontInAss（font_in_ass_enabled=true 时）
      3. 以上都不满足 → 告诉 Go 透传 Emby

    Query params（由 Go 透传）:
      path      : 原始请求路径（如 /emby/videos/123/Subtitles/1/0/Stream.ass）
      qs        : 原始 query string（如 api_key=xxx&...）
    """
    import re as _re
    original_path = request.query_params.get("path", "")
    query_string  = request.query_params.get("qs", "")

    if not original_path:
        return JSONResponse({"error": "missing path param"}, status_code=400)

    # ── 优先级1：内封字幕缓存命中 ────────────────────────────────────────────
    # 从路径中提取 itemId：/emby/videos/{itemId}/Subtitles/...
    m = _re.search(r"/videos/(\d+)/Subtitles", original_path, _re.IGNORECASE)
    if m:
        item_id = m.group(1)
        embedded_data = get_cached_embedded_sub(item_id)
        if embedded_data is not None:
            logger.info("[subtitle] 内封字幕缓存命中，直接返回给播放器: item_id=%s size=%d", item_id, len(embedded_data))
            return Response(
                content=embedded_data,
                status_code=200,
                media_type="text/plain; charset=utf-8",
                headers={"X-Subtitle-Source": "embedded-cache"},
            )

    # ── 优先级2：转发给 fontInAss ─────────────────────────────────────────────
    result = await proxy_to_font_in_ass(
        original_path=original_path,
        query_string=query_string,
        request_headers=dict(request.headers),
    )

    if result is None:
        # fontInAss 未启用或失败 → 告诉 Go 直接透传 Emby
        return JSONResponse({"action": "passthrough"}, status_code=200)

    status_code, body, headers = result
    return Response(
        content=body,
        status_code=status_code,
        headers=headers,
        media_type=headers.get("content-type", "text/plain; charset=utf-8"),
    )


@router.post("/subtitle/trigger")
async def subtitle_trigger(request: Request):
    """
    触发内封字幕异步提取。
    Go 在 302 成功后 fire-and-forget 调用此接口，不等待响应。

    Body JSON:
      item_id    : Emby item id
      cdn_url    : 115 CDN 直链（用于 ffmpeg 读取）
      user_agent : 播放器 UA（透传给 ffmpeg -user_agent）
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    item_id    = body.get("item_id", "")
    cdn_url    = body.get("cdn_url", "")
    user_agent = body.get("user_agent", "")

    if not item_id or not cdn_url:
        return JSONResponse({"error": "missing item_id or cdn_url"}, status_code=400)

    # 异步触发，不阻塞（内部已用 asyncio.create_task）
    await trigger_embedded_sub_extraction(item_id, cdn_url, user_agent)
    return {"accepted": True, "item_id": item_id}


@router.get("/subtitle/embedded/{item_id}")
async def subtitle_embedded(item_id: str):
    """
    返回已缓存的内封字幕（供 Go 字幕路由调用）。
    未命中返回 404，Go 回退到透传 Emby。
    """
    data = get_cached_embedded_sub(item_id)
    if data is None:
        return JSONResponse({"cached": False}, status_code=404)

    return Response(
        content=data,
        status_code=200,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Subtitle-Source": "embedded-cache",
            "Cache-Control": "no-cache",
        },
    )


@router.get("/subtitle/config")
async def subtitle_config():
    """
    返回当前字幕功能配置。
    Go 启动时或收到配置变更通知时调用，决定是否需要拦截字幕路由。
    """
    cfg = await _load_config()
    return {
        "font_in_ass_enabled": cfg.get("font_in_ass_enabled", "false").lower() == "true",
        "font_in_ass_url":     cfg.get("font_in_ass_url", ""),
        "embedded_sub_enabled": cfg.get("embedded_sub_enabled", "false").lower() == "true",
        "embedded_sub_tracks": cfg.get("embedded_sub_tracks", ""),
    }

