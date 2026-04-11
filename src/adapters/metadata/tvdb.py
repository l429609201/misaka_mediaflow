# src/adapters/metadata/tvdb.py
# TVDB 元数据源适配器
#
# The TVDB 是电视节目数据库，提供电视节目的元数据信息。
# API 文档: https://thetvdb.github.io/v4-api/

import logging
from typing import Any

from src.adapters.metadata.base import MetadataProvider, MetadataResult, MetaFieldSpec
from src.core.http_proxy import proxy_client

logger = logging.getLogger(__name__)

_BASE_URL = "https://api4.thetvdb.com/v4"


class TVDBProvider(MetadataProvider):
    """TVDB 元数据源"""

    PROVIDER_NAME = "tvdb"
    DISPLAY_NAME  = "TVDB"
    CONFIG_KEY    = "metadata_tvdb"

    CONFIG_FIELDS = [
        MetaFieldSpec(
            key="api_key",
            label="API Key",
            type="password",
            secret=True,
            placeholder="请输入 TVDB API Key",
            hint="在 thetvdb.com/dashboard/account/apikeys 获取 API Key",
        ),
    ]

    def __init__(self, api_key: str = "", **kwargs):
        self._api_key = api_key
        self._token = ""  # JWT token from login

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def _login(self) -> str:
        """使用 API Key 登录获取 JWT token"""
        if self._token:
            return self._token
        try:
            url = f"{_BASE_URL}/login"
            async with proxy_client(target_url=url, timeout=15) as client:
                resp = await client.post(url, json={"apikey": self._api_key},
                                          headers={"Content-Type": "application/json"})
                resp.raise_for_status()
                data = resp.json()
                self._token = data.get("data", {}).get("token", "")
                return self._token
        except Exception as e:
            logger.warning("[TVDB] 登录失败: %s", e)
            return ""

    async def _get(self, path: str, params: dict = None) -> Any:
        token = await self._login()
        if not token:
            return {}
        url = f"{_BASE_URL}{path}"
        async with proxy_client(target_url=url, timeout=15) as client:
            resp = await client.get(url, params=params,
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
            resp.raise_for_status()
            return resp.json()

    async def search(self, query: str, media_type: str = "movie", year: int = 0) -> list[MetadataResult]:
        try:
            tvdb_type = "movie" if media_type == "movie" else "series"
            params = {"query": query, "type": tvdb_type}
            if year:
                params["year"] = year
            data = await self._get("/search", params=params)
            items = data.get("data", [])
            results = []
            for item in items[:20]:
                tvdb_id = item.get("tvdb_id") or item.get("id", "")
                results.append(MetadataResult(
                    provider="tvdb",
                    media_type=media_type,
                    title=item.get("name", ""),
                    original_title=item.get("name", ""),
                    year=int(item.get("year", 0)) if item.get("year") else 0,
                    overview=item.get("overview", ""),
                    poster_url=item.get("image_url") or item.get("thumbnail", ""),
                    imdb_id=item.get("imdb_id", ""),
                    extra={"tvdb_id": tvdb_id},
                ))
            return results
        except Exception as e:
            logger.warning("[TVDB] 搜索失败: %s", e)
            return []

    async def get_detail(self, media_id: int | str, media_type: str = "movie") -> MetadataResult | None:
        try:
            path = f"/movies/{media_id}" if media_type == "movie" else f"/series/{media_id}"
            data = await self._get(path)
            item = data.get("data", {})
            return MetadataResult(
                provider="tvdb",
                media_type=media_type,
                title=item.get("name", ""),
                original_title=item.get("name", ""),
                year=int(item.get("year", 0)) if item.get("year") else 0,
                overview=item.get("overview", ""),
                poster_url=item.get("image", ""),
                extra={"tvdb_id": item.get("id")},
            )
        except Exception as e:
            logger.warning("[TVDB] 获取详情失败: %s", e)
            return None

    async def test_connection(self) -> bool:
        try:
            token = await self._login()
            return bool(token)
        except Exception:
            return False

    async def get_tv_seasons(self, media_id: int | str) -> dict | None:
        """获取 TVDB 剧集的季/集信息"""
        try:
            data = await self._get(f"/series/{media_id}/extended", params={"meta": "episodes"})
            item = data.get("data", {})
            if not item:
                return None
            seasons_raw = item.get("seasons", [])
            seasons = []
            for s in seasons_raw:
                stype = s.get("type", {}).get("type", "")
                if stype == "official":
                    seasons.append({
                        "season_number": s.get("number", 0),
                        "episode_count": len(s.get("episodes", [])),
                        "name": s.get("name", ""),
                        "overview": "",
                        "poster_path": s.get("image", ""),
                        "air_date": "",
                    })
            return {
                "name": item.get("name", ""),
                "overview": item.get("overview", ""),
                "poster_path": item.get("image", ""),
                "status": item.get("status", {}).get("name", ""),
                "seasons": seasons,
            }
        except Exception as e:
            logger.warning("[TVDB] get_tv_seasons 失败: %s", e)
            return None
