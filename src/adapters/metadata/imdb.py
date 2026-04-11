# src/adapters/metadata/imdb.py
# IMDB 元数据源适配器
#
# IMDB 是全球最大的电影数据库，提供电影、电视节目等作品的元数据信息。
# 支持两种数据源：
#   - 第三方 API (api.imdbapi.dev)：速度快，推荐使用
#   - 官方网站 HTML 解析：更稳定但速度较慢

import logging
from typing import Any

from src.adapters.metadata.base import MetadataProvider, MetadataResult, MetaFieldSpec
from src.core.http_proxy import proxy_client

logger = logging.getLogger(__name__)

_API_URL = "https://api.imdbapi.dev/v1"
_IMDB_URL = "https://www.imdb.com"


class ImdbProvider(MetadataProvider):
    """IMDB 元数据源"""

    PROVIDER_NAME = "imdb"
    DISPLAY_NAME  = "IMDB"
    CONFIG_KEY    = "metadata_imdb"

    CONFIG_FIELDS = [
        MetaFieldSpec(
            key="use_api",
            label="数据源",
            type="text",
            placeholder="true",
            hint="true=第三方API(推荐), false=官方网站HTML解析",
            default="true",
        ),
        MetaFieldSpec(
            key="enable_fallback",
            label="启用兜底",
            type="text",
            placeholder="true",
            hint="true=主方式失败时自动尝试另一种方式, false=不尝试",
            default="true",
        ),
    ]

    def __init__(self, use_api: str = "true", enable_fallback: str = "true", **kwargs):
        self._use_api = use_api.lower() in ("true", "1", "yes")
        self._enable_fallback = enable_fallback.lower() in ("true", "1", "yes")

    @property
    def available(self) -> bool:
        return True  # IMDB 不需要 API Key

    def _headers(self) -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    async def _api_search(self, query: str, media_type: str) -> list[MetadataResult]:
        """通过第三方 API 搜索"""
        try:
            resp = await proxy_client.get(
                f"{_API_URL}/search",
                params={"query": query},
                headers=self._headers(),
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("results", [])
            results = []
            for item in items[:20]:
                results.append(MetadataResult(
                    provider="imdb",
                    media_type=media_type,
                    title=item.get("title", ""),
                    original_title=item.get("originalTitle", "") or item.get("title", ""),
                    year=int(item.get("year", 0)) if item.get("year") else 0,
                    overview=item.get("plot", ""),
                    poster_url=item.get("poster", ""),
                    imdb_id=item.get("imdbId", ""),
                    vote_average=float(item.get("rating", 0)),
                    extra={"imdb_id": item.get("imdbId", "")},
                ))
            return results
        except Exception as e:
            logger.warning("[IMDB] API 搜索失败: %s", e)
            return []

    async def search(self, query: str, media_type: str = "movie", year: int = 0) -> list[MetadataResult]:
        if self._use_api:
            results = await self._api_search(query, media_type)
            if results or not self._enable_fallback:
                return results
            logger.info("[IMDB] API 无结果，尝试兜底")
        return await self._api_search(query, media_type)

    async def get_detail(self, media_id: int | str, media_type: str = "movie") -> MetadataResult | None:
        try:
            resp = await proxy_client.get(
                f"{_API_URL}/title/{media_id}",
                headers=self._headers(),
                timeout=15,
            )
            resp.raise_for_status()
            item = resp.json()
            genres = item.get("genres", [])
            return MetadataResult(
                provider="imdb",
                media_type=media_type,
                title=item.get("title", ""),
                original_title=item.get("originalTitle", ""),
                year=int(item.get("year", 0)) if item.get("year") else 0,
                overview=item.get("plot", ""),
                poster_url=item.get("poster", ""),
                imdb_id=str(media_id),
                vote_average=float(item.get("rating", 0)),
                genres=genres if isinstance(genres, list) else [],
                extra={"imdb_id": str(media_id)},
            )
        except Exception as e:
            logger.warning("[IMDB] 获取详情失败: %s", e)
            return None

    async def test_connection(self) -> bool:
        try:
            results = await self._api_search("test", "movie")
            return len(results) > 0
        except Exception:
            return False
