# app/adapters/media_server/emby.py
# Emby 适配器

import logging
from typing import Optional

import httpx

from src.adapters.media_server.base import MediaServerAdapter

logger = logging.getLogger(__name__)


class EmbyAdapter(MediaServerAdapter):
    """Emby 媒体服务器适配器"""

    def __init__(self, host: str, api_key: str):
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._host,
                timeout=30,
                params={"api_key": self._api_key},
            )
        return self._client

    async def get_libraries(self) -> list[dict]:
        client = await self._ensure_client()
        resp = await client.get("/emby/Library/VirtualFolders")
        return resp.json() if resp.status_code == 200 else []

    async def get_users(self) -> list[dict]:
        """获取 Emby 用户列表，返回 [{"id": ..., "name": ...}]"""
        client = await self._ensure_client()
        resp = await client.get("/emby/Users/Query")
        if resp.status_code != 200:
            return []
        data = resp.json()
        items = data.get("Items", []) if isinstance(data, dict) else data
        return [{"id": u.get("Id", ""), "name": u.get("Name", "")} for u in items if u.get("Id")]

    async def get_items(self, library_id: str, item_type: Optional[str] = None) -> list[dict]:
        client = await self._ensure_client()
        params = {
            "ParentId": library_id,
            "Recursive": "true",
            "Fields": "Path,MediaSources,ProviderIds",
        }
        if item_type:
            params["IncludeItemTypes"] = item_type
        resp = await client.get("/emby/Items", params=params)
        data = resp.json() if resp.status_code == 200 else {}
        return data.get("Items", [])

    async def get_item_detail(self, item_id: str) -> dict:
        client = await self._ensure_client()
        resp = await client.get(f"/emby/Items/{item_id}", params={
            "Fields": "Path,MediaSources,ProviderIds,Overview",
        })
        return resp.json() if resp.status_code == 200 else {}

    async def get_playback_info(self, item_id: str) -> dict:
        client = await self._ensure_client()
        resp = await client.get(f"/emby/Items/{item_id}/PlaybackInfo")
        return resp.json() if resp.status_code == 200 else {}

    async def test_connection(self) -> bool:
        try:
            client = await self._ensure_client()
            resp = await client.get("/emby/System/Info/Public")
            return resp.status_code == 200
        except Exception:
            return False

