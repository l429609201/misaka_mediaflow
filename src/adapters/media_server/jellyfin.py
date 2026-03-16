# app/adapters/media_server/jellyfin.py
# Jellyfin 适配器 — 与 Emby 共享大部分 API，路径前缀不同

import logging
from typing import Optional

import httpx

from src.adapters.media_server.base import MediaServerAdapter

logger = logging.getLogger(__name__)


class JellyfinAdapter(MediaServerAdapter):
    """Jellyfin 媒体服务器适配器"""

    def __init__(self, host: str, api_key: str):
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._host,
                timeout=30,
                headers={"Authorization": f'MediaBrowser Token="{self._api_key}"'},
            )
        return self._client

    async def get_libraries(self) -> list[dict]:
        client = await self._ensure_client()
        resp = await client.get("/Library/VirtualFolders")
        return resp.json() if resp.status_code == 200 else []

    async def get_items(self, library_id: str, item_type: Optional[str] = None) -> list[dict]:
        client = await self._ensure_client()
        params = {
            "ParentId": library_id,
            "Recursive": "true",
            "Fields": "Path,MediaSources,ProviderIds",
        }
        if item_type:
            params["IncludeItemTypes"] = item_type
        resp = await client.get("/Items", params=params)
        data = resp.json() if resp.status_code == 200 else {}
        return data.get("Items", [])

    async def get_item_detail(self, item_id: str) -> dict:
        client = await self._ensure_client()
        resp = await client.get(f"/Items/{item_id}", params={
            "Fields": "Path,MediaSources,ProviderIds,Overview",
        })
        return resp.json() if resp.status_code == 200 else {}

    async def get_playback_info(self, item_id: str) -> dict:
        client = await self._ensure_client()
        resp = await client.get(f"/Items/{item_id}/PlaybackInfo")
        return resp.json() if resp.status_code == 200 else {}

    async def test_connection(self) -> bool:
        try:
            client = await self._ensure_client()
            resp = await client.get("/System/Info/Public")
            return resp.status_code == 200
        except Exception:
            return False

