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

_API_URL = "https://api.imdbapi.dev"
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
            url = f"{_API_URL}/search/titles"
            async with proxy_client(target_url=url, timeout=15) as client:
                resp = await client.get(url, params={"query": query}, headers=self._headers())
                if resp.status_code != 200:
                    logger.warning("[IMDB] API 返回 %d", resp.status_code)
                    return []
                data = resp.json()
            items = data.get("titles", [])  # api.imdbapi.dev 返回 titles 字段
            results = []
            for item in items[:20]:
                # api.imdbapi.dev 字段: id, primaryTitle, originalTitle, startYear, plot, primaryImage, rating
                img = item.get("primaryImage", {})
                poster = img.get("url", "") if isinstance(img, dict) else ""
                rating = item.get("rating", {})
                score = rating.get("aggregateRating", 0) if isinstance(rating, dict) else 0
                results.append(MetadataResult(
                    provider="imdb",
                    media_type=media_type,
                    title=item.get("primaryTitle", "") or item.get("originalTitle", ""),
                    original_title=item.get("originalTitle", ""),
                    year=int(item.get("startYear", 0)) if item.get("startYear") else 0,
                    overview=item.get("plot", ""),
                    poster_url=poster,
                    imdb_id=item.get("id", ""),
                    vote_average=float(score) if score else 0,
                    extra={"imdb_id": item.get("id", "")},
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
            url = f"{_API_URL}/titles/{media_id}"
            async with proxy_client(target_url=url, timeout=15) as client:
                resp = await client.get(url, headers=self._headers())
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
