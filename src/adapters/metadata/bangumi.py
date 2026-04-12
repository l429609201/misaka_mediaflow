# src/adapters/metadata/bangumi.py
# Bangumi (BGM) 元数据源适配器（含 OAuth action）

import json
import logging
import secrets
from typing import Any

from src.adapters.metadata.base import MetadataProvider, MetadataResult, MetaFieldSpec
from src.core.http_proxy import proxy_client

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.bgm.tv"
_BGM_AUTH_URL = "https://bgm.tv/oauth/authorize"
_BGM_TOKEN_URL = "https://bgm.tv/oauth/access_token"
_BGM_OAUTH_KEY = "bangumi_oauth"


class BangumiProvider(MetadataProvider):
    """Bangumi (BGM) 元数据源"""

    PROVIDER_NAME = "bangumi"
    DISPLAY_NAME  = "Bangumi (BGM)"
    CONFIG_KEY    = "metadata_bangumi"

    CONFIG_FIELDS = [
        MetaFieldSpec(
            key="access_token",
            label="Access Token",
            type="password",
            secret=True,
            placeholder="请输入 Bangumi Access Token",
            hint="Token 模式: 在 next.bgm.tv/demo/access-token 获取，有效期最长1年",
        ),
        MetaFieldSpec(
            key="client_id",
            label="App ID (OAuth)",
            type="text",
            placeholder="OAuth 模式填写，Token 模式留空",
            hint="OAuth 模式: 在 bgm.tv/dev/app 创建应用后获取",
        ),
        MetaFieldSpec(
            key="client_secret",
            label="App Secret (OAuth)",
            type="password",
            secret=True,
            placeholder="OAuth 模式填写，Token 模式留空",
            hint="OAuth 模式: 应用密钥，请妥善保管",
        ),
        MetaFieldSpec(
            key="api_url",
            label="API 地址",
            type="text",
            placeholder="https://api.bgm.tv",
            hint="Bangumi API 地址，留空使用默认值",
            default="https://api.bgm.tv",
        ),
    ]

    def __init__(self, access_token: str = "", api_url: str = "", **kwargs):
        self._token = access_token
        self._base = (api_url or _BASE_URL).rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict:
        h = {"User-Agent": "MisakaMediaFlow/1.0", "Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def _get(self, path: str, params: dict = None) -> Any:
        url = f"{self._base}{path}"
        async with proxy_client(target_url=url, timeout=15) as client:
            resp = await client.get(url, params=params, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def search(self, query: str, media_type: str = "movie", year: int = 0) -> list[MetadataResult]:
        # Bangumi subject types: 1=book, 2=anime, 3=music, 4=game, 6=real
        bgm_type = 2 if media_type == "tv" else 6
        try:
            data = await self._get("/search/subject/" + query, params={"type": bgm_type, "responseGroup": "large"})
            items = data.get("list", []) if isinstance(data, dict) else []
            results = []
            for item in items[:20]:
                results.append(MetadataResult(
                    provider="bangumi",
                    media_type=media_type,
                    title=item.get("name_cn") or item.get("name", ""),
                    original_title=item.get("name", ""),
                    year=int(str(item.get("air_date", ""))[:4]) if item.get("air_date") else 0,
                    overview=item.get("summary", ""),
                    poster_url=item.get("images", {}).get("large", ""),
                    vote_average=item.get("rating", {}).get("score", 0),
                    extra={"bgm_id": item.get("id"), "url": item.get("url", "")},
                ))
            return results
        except Exception as e:
            logger.warning("[Bangumi] 搜索失败: %s", e)
            return []

    async def get_detail(self, media_id: int | str, media_type: str = "movie") -> MetadataResult | None:
        try:
            item = await self._get(f"/v0/subjects/{media_id}")
            return MetadataResult(
                provider="bangumi",
                media_type=media_type,
                title=item.get("name_cn") or item.get("name", ""),
                original_title=item.get("name", ""),
                year=int(str(item.get("date", ""))[:4]) if item.get("date") else 0,
                overview=item.get("summary", ""),
                poster_url=item.get("images", {}).get("large", ""),
                vote_average=item.get("rating", {}).get("score", 0),
                extra={"bgm_id": item.get("id")},
            )
        except Exception as e:
            logger.warning("[Bangumi] 获取详情失败: %s", e)
            return None

    async def test_connection(self) -> bool:
        try:
            data = await self._get("/v0/me")
            return bool(data.get("id"))
        except Exception:
            return False

    # ── OAuth 动态路由 ─────────────────────────────────────────────

    PRIVATE_ROUTES = [
        {"method": "POST", "path": "auth-url",       "summary": "获取 OAuth 授权链接"},
        {"method": "GET",  "path": "oauth-callback",  "summary": "OAuth 回调（bgm.tv 重定向）"},
        {"method": "POST", "path": "auth-state",      "summary": "获取授权状态"},
        {"method": "POST", "path": "logout",          "summary": "注销 OAuth 授权"},
    ]

    async def handle_private_route(self, path: str, method: str, payload: dict, **kwargs) -> dict:
        if path == "auth-url":
            return await self._action_auth_url(payload)
        elif path == "oauth-callback":
            return await self._action_exchange_code(payload)
        elif path == "auth-state":
            return await self._action_auth_state()
        elif path == "logout":
            return await self._action_logout()
        return {"error": f"不支持的路由: {method} /{path}"}

    @staticmethod
    async def _load_oauth() -> dict:
        from sqlalchemy import select
        from src.db import get_async_session_local
        from src.db.models import SystemConfig
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

    @staticmethod
    async def _save_oauth(data: dict):
        from sqlalchemy import select
        from src.db import get_async_session_local
        from src.db.models import SystemConfig
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

    async def _action_auth_url(self, payload: dict) -> dict:
        from src.api.v1.search_source import _load_json, _OVERRIDE_KEY
        from src.db import get_async_session_local
        async with get_async_session_local() as db:
            override_map = await _load_json(db, _OVERRIDE_KEY)
        client_id = override_map.get("bangumi", {}).get("client_id", "")
        if not client_id:
            return {"error": "请先在 Bangumi 配置中填写 App ID"}
        state = secrets.token_urlsafe(16)
        # redirect_uri 指向后端回调路由
        origin = payload.get("origin_url", "").rstrip("/")
        redirect_uri = f"{origin}/api/private/bangumi/oauth-callback"
        # 保存 state + redirect_uri，换码时直接取用，避免不一致
        oauth_data = await self._load_oauth()
        oauth_data["pending_state"] = state
        oauth_data["redirect_uri"] = redirect_uri
        await self._save_oauth(oauth_data)
        url = f"{_BGM_AUTH_URL}?client_id={client_id}&response_type=code&redirect_uri={redirect_uri}&state={state}"
        return {"url": url}

    async def _action_exchange_code(self, payload: dict) -> dict:
        """用授权码换取 token — redirect_uri 从 DB 取授权时保存的值"""
        from src.api.v1.search_source import _load_json, _save_json, _OVERRIDE_KEY
        from src.core.timezone import tm
        from src.db import get_async_session_local
        async with get_async_session_local() as db:
            override_map = await _load_json(db, _OVERRIDE_KEY)
        bgm_cfg = override_map.get("bangumi", {})
        client_id = bgm_cfg.get("client_id", "")
        client_secret = bgm_cfg.get("client_secret", "")
        if not client_id or not client_secret:
            return {"success": False, "message": "App ID 或 App Secret 未配置"}

        # redirect_uri 从 DB 取授权时保存的值，确保和 auth-url 完全一致
        oauth_data = await self._load_oauth()
        redirect_uri = oauth_data.get("redirect_uri", "") or payload.get("redirect_uri", "")

        try:
            async with proxy_client(target_url=_BGM_TOKEN_URL, timeout=15) as client:
                resp = await client.post(_BGM_TOKEN_URL, data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": payload.get("code", ""),
                    "redirect_uri": redirect_uri,
                }, headers={"Content-Type": "application/x-www-form-urlencoded"})
                resp.raise_for_status()
                token_data = resp.json()
        except Exception as e:
            return {"success": False, "message": f"换码失败: {e}"}
        access_token = token_data.get("access_token", "")
        if not access_token:
            return {"success": False, "message": "未获取到 access_token"}
        # 获取用户信息
        user_info = {}
        try:
            me_url = f"{_BASE_URL}/v0/me"
            async with proxy_client(target_url=me_url, timeout=10) as client:
                resp2 = await client.get(me_url,
                    headers={"Authorization": f"Bearer {access_token}", "User-Agent": "MisakaMediaFlow/1.0"})
                if resp2.status_code == 200:
                    user_info = resp2.json()
        except Exception:
            pass
        await self._save_oauth({
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token", ""),
            "expires_in": token_data.get("expires_in", 0),
            "authorized_at": tm.now(),
            "user_id": token_data.get("user_id") or user_info.get("id", 0),
            "nickname": user_info.get("nickname", ""),
            "username": user_info.get("username", ""),
            "avatar_url": user_info.get("avatar", {}).get("large", ""),
            "sign": user_info.get("sign", ""),
        })
        # 同步 token 到搜索源配置
        bgm_cfg["access_token"] = access_token
        override_map["bangumi"] = bgm_cfg
        async with get_async_session_local() as db:
            await _save_json(db, _OVERRIDE_KEY, override_map)
        from src.services.metadata_service import metadata_service
        metadata_service.invalidate_cache("bangumi")
        return {"success": True, "message": "授权成功"}

    async def _action_auth_state(self) -> dict:
        data = await self._load_oauth()
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

    async def _action_logout(self) -> dict:
        await self._save_oauth({})
        from src.api.v1.search_source import _load_json, _save_json, _OVERRIDE_KEY
        from src.db import get_async_session_local
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
