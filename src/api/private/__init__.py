# src/api/private/__init__.py
# Private API — 动态搜索源路由
#
# 架构:
#   每个 Provider 在类属性 PRIVATE_ROUTES 中声明自己需要的路径，
#   框架通过通配路由 /api/private/{provider}/{path} 自动分发。
#
# 路由规则:
#   POST /api/private/{provider}/{path}       ← 需认证，body 作为 payload
#   GET  /api/private/{provider}/{path}       ← 需认证，query 作为 payload
#   GET  /api/private/{provider}/oauth-callback ← 无需认证，OAuth 回调专用

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request, Body, Query
from fastapi.responses import HTMLResponse
from src.core.security import verify_token
from src.services.metadata_service import metadata_service
from src.adapters.metadata.factory import MetadataFactory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/private", tags=["Private API"])


# ── OAuth 回调（无需认证，bgm.tv 重定向过来带 code） ──────────────

@router.get("/{provider}/oauth-callback")
async def oauth_callback(provider: str, request: Request):
    """OAuth 回调 — bgm.tv 重定向到此，后端换码后返回 HTML 通知父窗口"""
    provider_cls = MetadataFactory.get_provider_class(provider)
    if not provider_cls:
        return HTMLResponse(_result_html("error", f"未知的搜索源: {provider}"))

    # 检查该 Provider 是否声明了 oauth-callback 路由
    routes = getattr(provider_cls, "PRIVATE_ROUTES", [])
    if not any(r.get("path") == "oauth-callback" for r in routes):
        return HTMLResponse(_result_html("error", f"搜索源 {provider} 不支持 OAuth 回调"))

    try:
        instance = MetadataFactory.create(provider)
        payload = dict(request.query_params)
        # 注入 origin_url 供 Provider 重建 redirect_uri
        origin = f"{request.url.scheme}://{request.url.netloc}"
        payload["origin_url"] = origin
        result = await instance.handle_private_route("oauth-callback", "GET", payload)

        if result.get("success"):
            return HTMLResponse(_result_html("success", result.get("message", "授权成功")))
        else:
            return HTMLResponse(_result_html("error", result.get("message", "授权失败")))
    except Exception as e:
        logger.warning("[Private API] %s/oauth-callback 失败: %s", provider, e)
        return HTMLResponse(_result_html("error", str(e)))


def _result_html(status: str, message: str) -> str:
    """OAuth 回调结果页 HTML — 通知父窗口后自动关闭"""
    color = "#52c41a" if status == "success" else "#ff4d4f"
    icon = "✓" if status == "success" else "✕"
    title = "授权成功" if status == "success" else "授权失败"
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title></head>
<body style="margin:0;display:flex;justify-content:center;align-items:center;height:100vh;
background:linear-gradient(135deg,#f09199 0%,#c06c84 100%);font-family:sans-serif">
<div style="background:#fff;padding:40px 50px;border-radius:12px;text-align:center;
box-shadow:0 10px 40px rgba(0,0,0,.1);min-width:300px">
<div style="font-size:48px;color:{color};margin-bottom:12px">{icon}</div>
<h2 style="margin:0 0 8px;color:#333">{title}</h2>
<p style="color:#666;margin:0 0 20px">{message}</p>
<button onclick="window.close()" style="padding:8px 24px;border:1px solid #d9d9d9;
border-radius:6px;background:#fff;cursor:pointer;font-size:14px">关闭窗口</button>
</div>
<script>
try {{ if(window.opener) {{ window.opener.postMessage('{status.upper()}_OAUTH_COMPLETE','*'); }} }} catch(e){{}}
setTimeout(function(){{ window.close() }}, 2000);
</script></body></html>"""


# ── 动态路由（需认证）──────────────────────────────────────────

@router.post("/{provider}/{path:path}", dependencies=[Depends(verify_token)])
async def private_post(
    provider: str, path: str,
    payload: Optional[Dict[str, Any]] = Body(None),
):
    """POST 动态路由 — Provider 自行分发"""
    return await _dispatch(provider, path, "POST", payload or {})


@router.get("/{provider}/{path:path}", dependencies=[Depends(verify_token)])
async def private_get(provider: str, path: str, request: Request):
    """GET 动态路由 — Provider 自行分发"""
    payload = dict(request.query_params)
    return await _dispatch(provider, path, "GET", payload)


async def _dispatch(provider: str, path: str, method: str, payload: dict) -> dict:
    """统一分发到 Provider.handle_private_route()"""
    provider_cls = MetadataFactory.get_provider_class(provider)
    if not provider_cls:
        return {"error": f"未知的搜索源: {provider}"}

    routes = getattr(provider_cls, "PRIVATE_ROUTES", [])
    if not any(r.get("path") == path for r in routes):
        return {"error": f"搜索源 {provider} 不支持路由: {method} /{path}"}

    try:
        instance = MetadataFactory.create(provider)
        return await instance.handle_private_route(path, method, payload)
    except Exception as e:
        logger.warning("[Private API] %s/%s 失败: %s", provider, path, e)
        return {"error": str(e)}
