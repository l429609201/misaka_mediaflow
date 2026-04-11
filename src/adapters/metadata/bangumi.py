# src/adapters/metadata/bangumi.py
# Bangumi (BGM) 元数据源适配器
#
# Bangumi 是 ACG 作品数据库，提供动画、漫画、游戏等作品的元数据信息。
# API 文档: https://bangumi.github.io/api/

import logging
from typing import Any

from src.adapters.metadata.base import MetadataProvider, MetadataResult, MetaFieldSpec
from src.core.http_proxy import proxy_client

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.bgm.tv"


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
