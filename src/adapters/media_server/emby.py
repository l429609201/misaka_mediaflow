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
            "Fields": "Path,MediaSources,ProviderIds,IndexNumber,ParentIndexNumber",
            "Limit": "10000",
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

    # ── 仪表盘扩展 ───────────────────────────────────────────────────

    async def get_system_info(self) -> dict:
        client = await self._ensure_client()
        resp = await client.get("/emby/System/Info")
        return resp.json() if resp.status_code == 200 else {}

    async def get_active_sessions(self) -> list[dict]:
        client = await self._ensure_client()
        resp = await client.get("/emby/Sessions")
        if resp.status_code != 200:
            return []
        sessions = resp.json()
        result = []
        for s in sessions:
            now_playing = s.get("NowPlayingItem")
            result.append({
                "id": s.get("Id", ""),
                "user_name": s.get("UserName", ""),
                "client": s.get("Client", ""),
                "device_name": s.get("DeviceName", ""),
                "remote_end_point": s.get("RemoteEndPoint", ""),
                "is_playing": now_playing is not None,
                "now_playing": {
                    "name": now_playing.get("Name", "") if now_playing else "",
                    "series_name": now_playing.get("SeriesName", "") if now_playing else "",
                    "type": now_playing.get("Type", "") if now_playing else "",
                } if now_playing else None,
                "play_state": {
                    "position_ticks": s.get("PlayState", {}).get("PositionTicks", 0),
                    "is_paused": s.get("PlayState", {}).get("IsPaused", False),
                    "is_muted": s.get("PlayState", {}).get("IsMuted", False),
                    "play_method": s.get("PlayState", {}).get("PlayMethod", ""),
                } if now_playing else None,
                "transcoding_info": {
                    "is_transcoding": bool(s.get("TranscodingInfo")),
                    "video_codec": s.get("TranscodingInfo", {}).get("VideoCodec", "") if s.get("TranscodingInfo") else "",
                    "audio_codec": s.get("TranscodingInfo", {}).get("AudioCodec", "") if s.get("TranscodingInfo") else "",
                    "completion_pct": s.get("TranscodingInfo", {}).get("CompletionPercentage", 0) if s.get("TranscodingInfo") else 0,
                } if s.get("TranscodingInfo") else None,
                "last_activity": s.get("LastActivityDate", ""),
            })
        return result

    async def get_item_counts(self) -> dict:
        client = await self._ensure_client()
        resp = await client.get("/emby/Items/Counts")
        if resp.status_code != 200:
            return {}
        data = resp.json()
        return {
            "movie_count": data.get("MovieCount", 0),
            "series_count": data.get("SeriesCount", 0),
            "episode_count": data.get("EpisodeCount", 0),
            "album_count": data.get("AlbumCount", 0),
            "song_count": data.get("SongCount", 0),
            "total": data.get("MovieCount", 0) + data.get("SeriesCount", 0) + data.get("EpisodeCount", 0),
        }

    async def get_activity_log(self, limit: int = 30) -> list[dict]:
        client = await self._ensure_client()
        resp = await client.get("/emby/System/ActivityLog/Entries", params={
            "StartIndex": 0, "Limit": limit
        })
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [
            {
                "id": e.get("Id", 0),
                "name": e.get("Name", ""),
                "type": e.get("Type", ""),
                "date": e.get("Date", ""),
                "severity": e.get("Severity", ""),
                "user_id": e.get("UserId", ""),
            }
            for e in data.get("Items", [])
        ]

