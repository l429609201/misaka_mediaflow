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
    process_embedded_sub_with_font_in_ass,
    get_cached_embedded_sub,
    get_embedded_sub_status,
    trigger_embedded_sub_extraction,
    warmup_embedded_subtitle,
    _load_config,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Internal-Subtitle"])


@router.get("/subtitle/proxy")
async def subtitle_proxy(request: Request):
    """
    字幕子集化主入口 — Go 反代拦截到 ASS/SRT 字幕请求后调用此接口。

    处理优先级：
      1. 内封字幕缓存命中 → 子集化后直接返回（无需从 Emby 拉取）
      2. 调用子集化引擎（内置 fonttools 或外置 fontInAss）从 Emby 拉取并处理
      3. 以上都不满足（未启用 / 引擎失败）→ 返回 action=passthrough 让 Go 透传

    Query params（由 Go 透传）:
      path    : 原始请求路径（如 /emby/Videos/123/Subtitles/1/0/Stream.ass）
      item_id : Go 从路由参数直接提取的 itemId（可选，用于避免正则解析）
      sub_id  : Go 从路由参数直接提取的 subId（可选）
      qs      : 原始 query string（如 api_key=xxx&...）
    """
    import re as _re
    original_path = request.query_params.get("path", "")
    query_string  = request.query_params.get("qs", "")
    # Go 新版本直接传 item_id/sub_id，省去正则解析
    item_id_param = request.query_params.get("item_id", "")
    sub_id_param  = request.query_params.get("sub_id", "")

    logger.info("[subtitle] proxy 被调用: path=%s item_id=%s sub_id=%s",
                original_path, item_id_param, sub_id_param)

    if not original_path:
        logger.warning("[subtitle] proxy: 缺少 path 参数")
        return JSONResponse({"error": "missing path param"}, status_code=400)

    # ── 优先级1：内封字幕缓存命中 → 直接返回（子集化已在提取时完成）────────────
    # item_id 优先使用 Go 直接传递的值，兜底用正则从 path 提取
    item_id = item_id_param
    if not item_id:
        m = _re.search(r"/videos/(\d+)/Subtitles", original_path, _re.IGNORECASE)
        if m:
            item_id = m.group(1)

    if item_id:
        embedded_data = get_cached_embedded_sub(item_id)
        if embedded_data is not None:
            logger.info("[subtitle] 命中内封字幕缓存: item_id=%s size=%d bytes", item_id, len(embedded_data))
            subsetted = await process_embedded_sub_with_font_in_ass(item_id, embedded_data)
            if subsetted is not None:
                logger.info("[subtitle] ✅ 内封字幕子集化完成: item_id=%s %d→%d bytes",
                            item_id, len(embedded_data), len(subsetted))
                return Response(
                    content=subsetted,
                    status_code=200,
                    media_type="text/x-ssa",
                    headers={"X-Subtitle-Source": "embedded-subsetted"},
                )
            # 子集化未启用或失败 → 直接返回原始内封字幕（不降级到 Emby）
            logger.info("[subtitle] 内封字幕直接返回(子集化未启用): item_id=%s size=%d bytes",
                        item_id, len(embedded_data))
            return Response(
                content=embedded_data,
                status_code=200,
                media_type="text/plain; charset=utf-8",
                headers={"X-Subtitle-Source": "embedded-raw"},
            )
        else:
            logger.debug("[subtitle] 无内封字幕缓存: item_id=%s，转入外挂字幕子集化", item_id)
    else:
        logger.debug("[subtitle] 无法提取 item_id，跳过内封字幕查询: path=%s", original_path)

    # ── 优先级2：外挂字幕子集化（从 Emby 拉取 → 引擎处理）──────────────────────
    logger.info("[subtitle] 开始外挂字幕子集化: path=%s qs=%s", original_path, query_string[:80] if query_string else "")
    result = await proxy_to_font_in_ass(
        original_path=original_path,
        query_string=query_string,
        request_headers=dict(request.headers),
    )

    if result is None:
        # 子集化引擎未启用或失败 → 告诉 Go 直接透传 Emby
        logger.info("[subtitle] ⚠️ 子集化未执行(引擎未启用或失败)，返回 passthrough: path=%s", original_path)
        return JSONResponse({"action": "passthrough"}, status_code=200)

    status_code, body, headers = result
    logger.info("[subtitle] ✅ 外挂字幕子集化完成: path=%s size=%d bytes content-type=%s",
                original_path, len(body), headers.get("content-type", "?"))
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
    item_type  = body.get("item_type", "")   # Emby Type: Movie / Episode / 空(兼容旧版)

    if not item_id or not cdn_url:
        return JSONResponse({"error": "missing item_id or cdn_url"}, status_code=400)

    # 异步触发，不阻塞（内部已用 asyncio.create_task）
    await trigger_embedded_sub_extraction(item_id, cdn_url, user_agent, item_type)
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

@router.get("/subtitle/embedded/{item_id}/status")
async def subtitle_embedded_status(item_id: str):
    """返回内封字幕缓存/提取状态，供 Go 在 PlaybackInfo 阶段轮询等待。"""
    return JSONResponse(get_embedded_sub_status(item_id))


@router.post("/subtitle/embedded/warmup")
async def subtitle_embedded_warmup(request: Request):
    """同步预热内封字幕，供 Go 在 PlaybackInfo 阶段调用。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    item_id = body.get("item_id", "")
    cdn_url = body.get("cdn_url", "")
    user_agent = body.get("user_agent", "")
    item_type = body.get("item_type", "")
    wait_timeout = float(body.get("wait_timeout", 3.5) or 3.5)

    if not item_id or not cdn_url:
        return JSONResponse({"error": "missing item_id or cdn_url"}, status_code=400)

    status = await warmup_embedded_subtitle(
        item_id=item_id,
        cdn_url=cdn_url,
        user_agent=user_agent,
        item_type=item_type,
        wait_timeout=wait_timeout,
    )
    return JSONResponse(status)


@router.get("/subtitle/config")
async def subtitle_config():
    """
    返回当前字幕功能配置。
    Go 启动时或收到配置变更通知时调用，决定是否需要拦截字幕路由。
    """
    cfg = await _load_config()
    return {
        "font_in_ass_enabled": cfg.get("font_in_ass_enabled", "false").lower() == "true",
        "font_in_ass_url": cfg.get("font_in_ass_url", ""),
        "embedded_sub_enabled": cfg.get("embedded_sub_enabled", "false").lower() == "true",
        "embedded_sub_tracks": cfg.get("embedded_sub_tracks", ""),
    }

