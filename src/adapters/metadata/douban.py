# src/adapters/metadata/douban.py
# 豆瓣元数据源适配器
#
# 豆瓣提供书籍、电影、音乐等作品信息。
# 由于豆瓣没有公开 API，使用 Cookie 方式访问网页接口。

import logging
from typing import Any

from src.adapters.metadata.base import MetadataProvider, MetadataResult, MetaFieldSpec
from src.core.http_proxy import proxy_client

logger = logging.getLogger(__name__)

_BASE_URL = "https://movie.douban.com"
_API_URL = "https://frodo.douban.com/api/v2"


class DoubanProvider(MetadataProvider):
    """豆瓣元数据源"""

    PROVIDER_NAME = "douban"
    DISPLAY_NAME  = "豆瓣"
    CONFIG_KEY    = "metadata_douban"

    # 固定 API Key，不暴露给前端配置
    _DOUBAN_API_KEY = "0ac44ae016490db2204ce0a042db2916"

    CONFIG_FIELDS = [
        MetaFieldSpec(
            key="cookie",
            label="Cookie",
            type="textarea",
            placeholder="bid=xxx; dbcl2=xxx; ...",
            hint="在浏览器中登录豆瓣后，打开开发者工具(F12)，在 Network 标签页中找到任意请求，复制 Cookie 值",
        ),
    ]

    def __init__(self, cookie: str = "", **kwargs):
        self._cookie = cookie
        self._api_key = self._DOUBAN_API_KEY

    @property
    def available(self) -> bool:
        return bool(self._cookie)

    def _headers(self) -> dict:
        h = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://movie.douban.com/",
            "Accept": "application/json",
        }
        if self._cookie:
            h["Cookie"] = self._cookie
        return h

    async def _get(self, url: str, params: dict = None) -> Any:
        async with proxy_client(target_url=url, timeout=15) as client:
            resp = await client.get(url, params=params, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def search(self, query: str, media_type: str = "movie", year: int = 0) -> list[MetadataResult]:
        try:
            params = {"q": query, "apikey": self._api_key, "count": 20}
            search_type = "movie" if media_type == "movie" else "tv"
            data = await self._get(f"{_API_URL}/search/movie", params=params)
            items = data.get("items", [])
            results = []
            for entry in items:
                item = entry.get("target", entry)
                cover = item.get("cover_url") or item.get("pic", {}).get("large", "")
                results.append(MetadataResult(
                    provider="douban",
                    media_type=media_type,
                    title=item.get("title", ""),
                    original_title=item.get("original_title", ""),
                    year=int(item.get("year", 0)) if item.get("year") else 0,
                    overview=item.get("card_subtitle", ""),
                    poster_url=cover,
                    vote_average=float(item.get("rating", {}).get("value", 0)),
                    extra={"douban_id": item.get("id"), "uri": item.get("uri", "")},
                ))
            return results
        except Exception as e:
            logger.warning("[Douban] 搜索失败: %s", e)
            return []

    async def get_detail(self, media_id: int | str, media_type: str = "movie") -> MetadataResult | None:
        try:
            params = {"apikey": self._api_key}
            data = await self._get(f"{_API_URL}/movie/{media_id}", params=params)
            genres = [g for g in data.get("genres", [])]
            return MetadataResult(
                provider="douban",
                media_type=media_type,
                title=data.get("title", ""),
                original_title=data.get("original_title", ""),
                year=int(data.get("year", 0)) if data.get("year") else 0,
                overview=data.get("intro", ""),
                poster_url=data.get("pic", {}).get("large", ""),
                vote_average=float(data.get("rating", {}).get("value", 0)),
                genres=genres,
                extra={"douban_id": data.get("id")},
            )
        except Exception as e:
            logger.warning("[Douban] 获取详情失败: %s", e)
            return None

    async def test_connection(self) -> bool:
        try:
            data = await self._get(f"{_API_URL}/search/movie", params={"q": "test", "apikey": self._api_key, "count": 1})
            return "items" in data
        except Exception:
            return False
