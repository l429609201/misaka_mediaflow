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
        return True  # Cookie 可选，有内置 API Key 即可搜索

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
        """参照弹幕库: movie.douban.com/j/search_subjects"""
        try:
            search_type = "movie" if media_type == "movie" else "tv"
            url = f"{_BASE_URL}/j/search_subjects"
            params = {"type": search_type, "tag": query, "page_limit": 20, "page_start": 0}
            data = await self._get(url, params=params)
            items = data.get("subjects", [])
            results = []
            for item in items:
                rate = item.get("rate", "0")
                results.append(MetadataResult(
                    provider="douban",
                    media_type=media_type,
                    title=item.get("title", ""),
                    poster_url=item.get("cover", ""),
                    vote_average=float(rate) if rate else 0,
                    extra={"douban_id": item.get("id", ""), "url": item.get("url", "")},
                ))
            return results
        except Exception as e:
            logger.warning("[Douban] 搜索失败: %s", e)
            return []

    async def get_detail(self, media_id: int | str, media_type: str = "movie") -> MetadataResult | None:
        """参照弹幕库: HTML 解析 movie.douban.com/subject/{id}/"""
        import re
        try:
            url = f"{_BASE_URL}/subject/{media_id}/"
            async with proxy_client(target_url=url, timeout=15) as client:
                resp = await client.get(url, headers=self._headers())
                if resp.status_code != 200:
                    return None
                html = resp.text

            title = ""
            title_match = re.search(r'<span property="v:itemreviewed">(.*?)</span>', html)
            if title_match:
                title = title_match.group(1).strip()

            year_val = 0
            year_match = re.search(r'<span class="year">\((\d{4})\)</span>', html)
            if year_match:
                year_val = int(year_match.group(1))

            imdb_id = ""
            imdb_match = re.search(r'<a href="https://www.imdb.com/title/(tt\d+)"', html)
            if imdb_match:
                imdb_id = imdb_match.group(1)

            return MetadataResult(
                provider="douban",
                media_type=media_type,
                title=title,
                year=year_val,
                imdb_id=imdb_id,
                extra={"douban_id": str(media_id)},
            )
        except Exception as e:
            logger.warning("[Douban] 获取详情失败: %s", e)
            return None

    async def test_connection(self) -> bool:
        """测试豆瓣连接 — 直接访问 movie.douban.com"""
        try:
            url = f"{_BASE_URL}/j/search_subjects"
            params = {"type": "movie", "tag": "test", "page_limit": 1, "page_start": 0}
            data = await self._get(url, params=params)
            return "subjects" in data
        except Exception:
            return False
