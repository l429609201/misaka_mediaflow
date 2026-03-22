# src/api/redirect_url.py
# 对外统一 302 入口 — 对齐 P115StrmHelper redirect_url 协议
#
# 支持:
#   GET  /redirect_url
#   POST /redirect_url
#   HEAD /redirect_url
#   GET  /redirect_url/{args:path}
#   POST /redirect_url/{args:path}
#   HEAD /redirect_url/{args:path}
#
# 参数:
#   pickcode / pick_code / path / url / file_name / share_code / receive_code / item_id

import logging
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse

from src.services.redirect_service import RedirectService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Redirect"])

_redirect_service = RedirectService()

# ── 公共参数提取 ────────────────────────────────────────────────────────────


def _extract_params(request: Request, args_path: str = "") -> dict:
    """从 request.query_params 提取所有支持的参数"""
    q = request.query_params
    return dict(
        pickcode=q.get("pickcode", "") or q.get("pick_code", ""),
        pick_code="",           # 已合并到 pickcode
        args_path=args_path,
        path=q.get("path", ""),
        url=q.get("url", ""),
        file_name=q.get("file_name", "") or q.get("filename", ""),
        share_code=q.get("share_code", ""),
        receive_code=q.get("receive_code", ""),
        item_id=q.get("item_id", ""),
        storage_id=int(q.get("storage_id", 0) or 0),
        api_key=q.get("api_key", "") or q.get("X-Emby-Token", ""),
    )


async def _handle(request: Request, args_path: str = ""):
    """统一处理逻辑：解析 → 302 或错误"""
    params = _extract_params(request, args_path)
    result = await _redirect_service.resolve_any(**params)

    if result.get("url"):
        logger.info("[redirect_url] 302 → source=%s", result.get("source"))
        return RedirectResponse(url=result["url"], status_code=302)

    logger.warning("[redirect_url] 解析失败: %s params=%s", result.get("error"), params)
    return JSONResponse(
        status_code=200,   # 保持 200 以免播放器重试循环，错误信息在 body
        content={"error": result.get("error", "resolve failed"), "source": result.get("source", "")}
    )


# ── 基础入口（无 path 参数）───────────────────────────────────────────────


@router.get("/redirect_url", include_in_schema=True, summary="统一302入口")
async def redirect_url_get(request: Request):
    """GET /redirect_url — 支持 ?pickcode= / ?path= / ?url= / ?item_id= 等参数"""
    return await _handle(request)


@router.post("/redirect_url", include_in_schema=True, summary="统一302入口(POST)")
async def redirect_url_post(request: Request):
    """POST /redirect_url — 兼容中间层/插件 POST 触发场景"""
    return await _handle(request)


@router.head("/redirect_url", include_in_schema=True, summary="统一302入口(HEAD)")
async def redirect_url_head(request: Request):
    """HEAD /redirect_url — 播放器探测"""
    return await _handle(request)


# ── 路径拼接入口 ─────────────────────────────────────────────────────────


@router.get("/redirect_url/{args:path}", include_in_schema=True, summary="路径式302入口")
async def redirect_url_path_get(args: str, request: Request):
    """GET /redirect_url/{args} — 路径拼接方式，args 视为挂载路径或云端路径"""
    return await _handle(request, args_path=args)


@router.post("/redirect_url/{args:path}", include_in_schema=True, summary="路径式302入口(POST)")
async def redirect_url_path_post(args: str, request: Request):
    """POST /redirect_url/{args}"""
    return await _handle(request, args_path=args)


@router.head("/redirect_url/{args:path}", include_in_schema=True, summary="路径式302入口(HEAD)")
async def redirect_url_path_head(args: str, request: Request):
    """HEAD /redirect_url/{args}"""
    return await _handle(request, args_path=args)

