# src/api/v1/bangumi_oauth.py
# Bangumi OAuth 授权流程 API
#
# OAuth 流程:
#   1. 前端调 /auth-url 获取授权链接，弹窗打开
#   2. 用户在 bgm.tv 授权后重定向到 /bgm-oauth-callback
#   3. 前端回调页调 /exchange-code 用 code 换 token
#   4. 后端存 token 到 SystemConfig，通知父窗口刷新

import json
import logging
import secrets

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.core.http_proxy import proxy_client
from src.core.security import verify_token
from src.core.timezone import tm
from src.db import get_async_session_local
from src.db.models import SystemConfig
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search-source/bangumi", tags=["bangumi-oauth"])

_BGM_OAUTH_KEY = "bangumi_oauth"
_BGM_AUTH_URL = "https://bgm.tv/oauth/authorize"
_BGM_TOKEN_URL = "https://bgm.tv/oauth/access_token"
_BGM_API_URL = "https://api.bgm.tv"


async def _load_oauth() -> dict:
    async with get_async_session_local() as db:
        row = (await db.execute(
            select(SystemConfig).where(SystemConfig.key == _BGM_OAUTH_KEY)
        )).scalars().first()
        if row and row.value:
            try:
                return json.loads(row.value)
            except Exception:
                pass
    return {}


async def _save_oauth(data: dict):
    async with get_async_session_local() as db:
        row = (await db.execute(
            select(SystemConfig).where(SystemConfig.key == _BGM_OAUTH_KEY)
        )).scalars().first()
        val = json.dumps(data, ensure_ascii=False)
        if row:
            row.value = val
        else:
            db.add(SystemConfig(key=_BGM_OAUTH_KEY, value=val, description="Bangumi OAuth"))
        await db.commit()


class AuthUrlPayload(BaseModel):
    redirect_uri: str


class ExchangeCodePayload(BaseModel):
    code: str
    state: str = ""
    redirect_uri: str


@router.post("/auth-url", dependencies=[Depends(verify_token)])
async def get_auth_url(payload: AuthUrlPayload):
    """生成 Bangumi OAuth 授权链接"""
    # 从搜索源配置读取 client_id
    from src.api.v1.search_source import _load_json, _OVERRIDE_KEY
    async with get_async_session_local() as db:
        override_map = await _load_json(db, _OVERRIDE_KEY)
    bgm_cfg = override_map.get("bangumi", {})
    client_id = bgm_cfg.get("client_id", "")

    if not client_id:
        return {"error": "请先在 Bangumi 配置中填写 App ID"}

    state = secrets.token_urlsafe(16)
    # 临时保存 state 用于验证
    oauth_data = await _load_oauth()
    oauth_data["pending_state"] = state
    await _save_oauth(oauth_data)

    url = (
        f"{_BGM_AUTH_URL}"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&redirect_uri={payload.redirect_uri}"
        f"&state={state}"
    )
    return {"url": url}


@router.post("/exchange-code", dependencies=[Depends(verify_token)])
async def exchange_code(payload: ExchangeCodePayload):
    """用授权码换取 access_token"""
    from src.api.v1.search_source import _load_json, _save_json, _OVERRIDE_KEY
    async with get_async_session_local() as db:
        override_map = await _load_json(db, _OVERRIDE_KEY)
    bgm_cfg = override_map.get("bangumi", {})
    client_id = bgm_cfg.get("client_id", "")
    client_secret = bgm_cfg.get("client_secret", "")

    if not client_id or not client_secret:
        return {"success": False, "message": "App ID 或 App Secret 未配置"}

    try:
        async with proxy_client(target_url=_BGM_TOKEN_URL, timeout=15) as client:
            resp = await client.post(_BGM_TOKEN_URL, data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": payload.code,
                "redirect_uri": payload.redirect_uri,
            }, headers={"Content-Type": "application/x-www-form-urlencoded"})
            resp.raise_for_status()
            token_data = resp.json()
    except Exception as e:
        logger.warning("[BGM OAuth] 换码失败: %s", e)
        return {"success": False, "message": f"换码失败: {e}"}

    access_token = token_data.get("access_token", "")
    if not access_token:
        return {"success": False, "message": "未获取到 access_token"}

    # 获取用户信息
    user_info = {}
    try:
        me_url = f"{_BGM_API_URL}/v0/me"
        async with proxy_client(target_url=me_url, timeout=10) as client:
            resp2 = await client.get(me_url,
                headers={"Authorization": f"Bearer {access_token}", "User-Agent": "MisakaMediaFlow/1.0"})
            if resp2.status_code == 200:
                user_info = resp2.json()
    except Exception:
        pass

    # 保存 OAuth 数据
    oauth_data = {
        "access_token": access_token,
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_in": token_data.get("expires_in", 0),
        "authorized_at": tm.now(),
        "user_id": token_data.get("user_id") or user_info.get("id", 0),
        "nickname": user_info.get("nickname", ""),
        "username": user_info.get("username", ""),
        "avatar_url": user_info.get("avatar", {}).get("large", ""),
        "sign": user_info.get("sign", ""),
    }
    await _save_oauth(oauth_data)

    # 同步 access_token 到搜索源配置，让 BangumiProvider 能用
    from src.api.v1.search_source import _load_json, _save_json, _OVERRIDE_KEY
    async with get_async_session_local() as db:
        override_map = await _load_json(db, _OVERRIDE_KEY)
    bgm_cfg = override_map.get("bangumi", {})
    bgm_cfg["access_token"] = access_token
    override_map["bangumi"] = bgm_cfg
    async with get_async_session_local() as db:
        await _save_json(db, _OVERRIDE_KEY, override_map)

    # 清除 Provider 缓存
    from src.services.metadata_service import metadata_service
    metadata_service.invalidate_cache("bangumi")

    return {"success": True, "message": "授权成功"}


@router.get("/auth-state", dependencies=[Depends(verify_token)])
async def get_auth_state():
    """获取 BGM OAuth 授权状态"""
    data = await _load_oauth()
    if not data.get("access_token"):
        return {"isAuthenticated": False}

    return {
        "isAuthenticated": True,
        "bangumiUserId": data.get("user_id", 0),
        "nickname": data.get("nickname", ""),
        "username": data.get("username", ""),
        "avatarUrl": data.get("avatar_url", ""),
        "sign": data.get("sign", ""),
        "authorizedAt": data.get("authorized_at", ""),
    }


@router.post("/logout", dependencies=[Depends(verify_token)])
async def logout():
    """注销 BGM OAuth 授权"""
    await _save_oauth({})

    # 清除搜索源配置中的 access_token
    from src.api.v1.search_source import _load_json, _save_json, _OVERRIDE_KEY
    async with get_async_session_local() as db:
        override_map = await _load_json(db, _OVERRIDE_KEY)
    bgm_cfg = override_map.get("bangumi", {})
    bgm_cfg.pop("access_token", None)
    override_map["bangumi"] = bgm_cfg
    async with get_async_session_local() as db:
        await _save_json(db, _OVERRIDE_KEY, override_map)

    from src.services.metadata_service import metadata_service
    metadata_service.invalidate_cache("bangumi")

    return {"success": True}
