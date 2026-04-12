# src/adapters/metadata/imdb.py
# IMDB 元数据源适配器（参照弹幕库 ImdbMetadataSource）
#
# 两种搜索模式:
#   - 第三方 API (api.imdbapi.dev) — 可能被 Cloudflare 403
#   - IMDB Suggestion API (v3.sg.media-imdb.com) — 更稳定

import logging
from typing import Any

from src.adapters.metadata.base import MetadataProvider, MetadataResult, MetaFieldSpec
from src.core.http_proxy import proxy_client

logger = logging.getLogger(__name__)

_API_URL = "https://api.imdbapi.dev"
_SUGGEST_URL = "https://v3.sg.media-imdb.com/suggestion/titles/x"


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
            hint="true=第三方API, false=IMDB官方Suggestion接口(更稳定)",
            default="true",
        ),
        MetaFieldSpec(
            key="enable_fallback",
            label="启用兜底",
            type="text",
            placeholder="true",
            hint="true=主方式失败时自动尝试另一种方式",
            default="true",
        ),
    ]

    def __init__(self, use_api: str = "true", enable_fallback: str = "true", **kwargs):
        self._use_api = use_api.lower() in ("true", "1", "yes")
        self._enable_fallback = enable_fallback.lower() in ("true", "1", "yes")

    @property
    def available(self) -> bool:
        return True

    def _headers(self) -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }

    # ── 模式1: 第三方 API (api.imdbapi.dev) ────────────────────────

    async def _api_search(self, query: str, media_type: str) -> list[MetadataResult]:
        try:
            url = f"{_API_URL}/search/titles"
            async with proxy_client(target_url=url, timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, params={"query": query}, headers=self._headers())
                if resp.status_code != 200:
                    ct = resp.headers.get("content-type", "")
                    body = resp.text[:200] if resp.text else ""
                    logger.warning("[IMDB] API 返回 %d, content-type=%s, body=%s", resp.status_code, ct, body)
                    return []
                data = resp.json()
            results = []
            for item in data.get("titles", [])[:20]:
                img = item.get("primaryImage", {})
                poster = img.get("url", "") if isinstance(img, dict) else ""
                rating = item.get("rating", {})
                score = rating.get("aggregateRating", 0) if isinstance(rating, dict) else 0
                results.append(MetadataResult(
                    provider="imdb", media_type=media_type,
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

    # ── 模式2: IMDB Suggestion API (参照弹幕库) ───────────────────

    async def _suggest_search(self, query: str, media_type: str) -> list[MetadataResult]:
        """IMDB 官方 suggestion JSON — 更稳定，不被 Cloudflare 拦截"""
        try:
            keyword = query.strip().lower()
            if not keyword:
                return []
            url = f"{_SUGGEST_URL}/{keyword}.json"
            async with proxy_client(target_url=url, timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers=self._headers())
                if resp.status_code != 200:
                    logger.warning("[IMDB] Suggestion API 返回 %d", resp.status_code)
                    return []
                data = resp.json()
            results = []
            for item in data.get("d", []):
                # q 字段: feature/tvSeries/tvMovie/tvMiniSeries 等
                q = item.get("q", "")
                if q not in ("feature", "tvSeries", "tvMovie", "tvMiniSeries", "video", "tvSpecial"):
                    continue
                img = item.get("i", {})
                poster = img.get("imageUrl", "") if isinstance(img, dict) else ""
                results.append(MetadataResult(
                    provider="imdb", media_type=media_type,
                    title=item.get("l", ""),
                    year=int(item.get("y", 0)) if item.get("y") else 0,
                    poster_url=poster,
                    imdb_id=item.get("id", ""),
                    overview=item.get("s", ""),  # 演员列表
                    extra={"imdb_id": item.get("id", "")},
                ))
            return results
        except Exception as e:
            logger.warning("[IMDB] Suggestion 搜索失败: %s", e)
            return []

    # ── 对外接口 ──────────────────────────────────────────────────

    async def search(self, query: str, media_type: str = "movie", year: int = 0) -> list[MetadataResult]:
        primary = self._api_search if self._use_api else self._suggest_search
        fallback = self._suggest_search if self._use_api else self._api_search

        results = await primary(query, media_type)
        if results:
            return results
        if self._enable_fallback:
            mode = "Suggestion" if self._use_api else "API"
            logger.info("[IMDB] 主模式无结果/失败，切换到 %s", mode)
            return await fallback(query, media_type)
        return []

    async def get_detail(self, media_id: int | str, media_type: str = "movie") -> MetadataResult | None:
        try:
            url = f"{_API_URL}/titles/{media_id}"
            async with proxy_client(target_url=url, timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers=self._headers())
                if resp.status_code != 200:
                    return None
                item = resp.json()
            return MetadataResult(
                provider="imdb", media_type=media_type,
                title=item.get("primaryTitle", "") or item.get("originalTitle", ""),
                original_title=item.get("originalTitle", ""),
                year=int(item.get("startYear", 0)) if item.get("startYear") else 0,
                overview=item.get("plot", ""),
                poster_url=(item.get("primaryImage", {}) or {}).get("url", ""),
                imdb_id=str(media_id),
                vote_average=float((item.get("rating", {}) or {}).get("aggregateRating", 0)),
                genres=item.get("genres", []),
                extra={"imdb_id": str(media_id)},
            )
        except Exception as e:
            logger.warning("[IMDB] 获取详情失败: %s", e)
            return None

    async def test_connection(self) -> bool:
        """用 Suggestion API 测试（不需要 API Key，不被 Cloudflare 拦截）"""
        try:
            url = f"{_SUGGEST_URL}/test.json"
            async with proxy_client(target_url=url, timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False
