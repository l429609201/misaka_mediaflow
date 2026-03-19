 
# src/adapters/metadata/tmdb.py
# TMDB 元数据源适配器 — 纯适配器层，不碰数据库
#
# 配置通过构造函数注入，由 service 层从 SystemConfig 读取后传入。
# 自动走代理中间件（core.http_proxy 启动时已由 service 层注入配置）。
#
# 多语言搜索策略:
#   _lang_chain = [primary] + fallback_languages（去重保序）
#
#   ① _get_with_fallback  — 主语言无结果才试下一个（优先主语言）
#   ② search_multilang    — 每个语言都搜一遍，按 tmdb_id 去重合并
#      适合标题在各语言区名称不同的情况

import logging
from typing import Any

from src.adapters.metadata.base import MetadataProvider, MetadataResult
from src.core.http_proxy import proxy_client

logger = logging.getLogger(__name__)

_BASE_URL   = "https://api.themoviedb.org/3"
_IMAGE_BASE = "https://image.tmdb.org/t/p"

# 剧集组类型枚举（TMDB 官方定义）
EPISODE_GROUP_TYPES: dict[int, str] = {
    1: "Original Air Date",
    2: "Absolute",
    3: "DVD",
    4: "Digital",
    5: "Story Arc",
    6: "Production",
    7: "TV",
}


class TMDBProvider(MetadataProvider):
    """TMDB 元数据源"""

    PROVIDER_NAME = "tmdb"
    DISPLAY_NAME  = "TMDB"
    CONFIG_KEY    = "metadata_tmdb"

    def __init__(
        self,
        api_key: str = "",
        language: str = "zh-CN",
        fallback_languages: list[str] | None = None,
    ):
        self._api_key    = api_key
        self._language   = language
        self._lang_chain = self._build_lang_chain(language, fallback_languages)

    def reconfigure(
        self,
        api_key: str = "",
        language: str = "zh-CN",
        fallback_languages: list[str] | None = None,
    ) -> None:
        """运行时刷新配置（前端保存后由 service 层调用）"""
        self._api_key    = api_key
        self._language   = language
        self._lang_chain = self._build_lang_chain(language, fallback_languages)

    @staticmethod
    def _build_lang_chain(primary: str, fallbacks: list[str] | None) -> list[str]:
        """构建语言回退链（去重、保序）"""
        seen: set[str] = set()
        chain: list[str] = []
        for lang in [primary] + (fallbacks or []):
            if lang and lang not in seen:
                chain.append(lang)
                seen.add(lang)
        return chain

    # ──────────────────────────────────────────────────────────────────
    #  底层请求
    # ──────────────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None, language: str = "") -> dict:
        """统一 GET，自动附加 api_key / language，自动走代理"""
        if not self._api_key:
            logger.warning("[TMDB] API Key 未配置")
            return {}

        url = f"{_BASE_URL}{path}"
        merged: dict[str, Any] = {
            "api_key":  self._api_key,
            "language": language or self._language,
            **(params or {}),
        }
        try:
            async with proxy_client(target_url=url, timeout=15) as client:
                resp = await client.get(url, params=merged)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 401:
                    logger.error("[TMDB] API Key 无效 (401)")
                elif resp.status_code == 404:
                    logger.debug("[TMDB] 未找到: %s", path)
                else:
                    logger.warning("[TMDB] HTTP %d: %s", resp.status_code, path)
        except Exception as e:
            logger.error("[TMDB] 请求异常: %s → %s", path, e)
        return {}

    async def _get_with_fallback(self, path: str, params: dict | None = None) -> dict:
        """
        带语言回退的 GET。
        results 为空时依次尝试 _lang_chain 中的后备语言。
        非 results 型接口（detail / images）直接返回第一次结果。
        """
        for lang in self._lang_chain:
            data    = await self._get(path, params, language=lang)
            results = data.get("results")
            if results is None:
                return data
            if results:
                if lang != self._language:
                    logger.debug("[TMDB] 回退语言生效: %s", lang)
                return data
        return {}

    # ──────────────────────────────────────────────────────────────────
    #  MetadataProvider 接口
    # ──────────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def test_connection(self) -> bool:
        data = await self._get("/configuration")
        return bool(data.get("images"))

    async def search(self, query: str, media_type: str = "movie", year: int = 0) -> list[MetadataResult]:
        """搜索电影或电视剧，自动语言回退"""
        is_tv    = media_type in ("tv", "series")
        endpoint = "/search/tv" if is_tv else "/search/movie"
        params: dict[str, Any] = {"query": query}
        if year:
            params["first_air_date_year" if is_tv else "year"] = year
        data = await self._get_with_fallback(endpoint, params)
        return self._parse_list(data.get("results", []), "tv" if is_tv else "movie")

    async def get_detail(self, media_id: int | str, media_type: str = "movie") -> MetadataResult | None:
        is_tv = media_type in ("tv", "series")
        data  = await self._get(f"/{'tv' if is_tv else 'movie'}/{media_id}")
        return self._parse_detail(data, "tv" if is_tv else "movie") if data else None

    async def get_images(self, media_id: int | str, media_type: str = "movie") -> dict:
        is_tv    = media_type in ("tv", "series")
        lang_pfx = self._language[:2]
        data = await self._get(
            f"/{'tv' if is_tv else 'movie'}/{media_id}/images",
            {"include_image_language": f"{lang_pfx},en,null"},
            language="",
        )
        return {
            "posters":   [self._img(p["file_path"]) for p in data.get("posters",   [])[:10] if p.get("file_path")],
            "backdrops": [self._img(p["file_path"], "w780") for p in data.get("backdrops", [])[:10] if p.get("file_path")],
        }

    async def find_by_external_id(self, external_id: str, source: str = "imdb") -> MetadataResult | None:
        source_map = {"imdb": "imdb_id", "tvdb": "tvdb_id", "wikidata": "wikidata_id"}
        data = await self._get(
            f"/find/{external_id}",
            {"external_source": source_map.get(source, f"{source}_id")},
        )
        for item in data.get("movie_results", []):
            return self._parse_list([item], "movie")[0]
        for item in data.get("tv_results", []):
            return self._parse_list([item], "tv")[0]
        return None

    # ──────────────────────────────────────────────────────────────────
    #  综合搜索 /search/multi
    # ──────────────────────────────────────────────────────────────────

    async def search_multi(
        self,
        query: str,
        page: int = 1,
        include_adult: bool = False,
    ) -> dict:
        """
        综合搜索：一次请求同时搜索电影、电视剧、演员，自动语言回退。

        Returns:
            {
                "movies":  [MetadataResult, ...],
                "tv":      [MetadataResult, ...],
                "persons": [{"id", "name", "profile_url", "known_for"}, ...],
                "raw":     [...]
            }
        """
        data = await self._get_with_fallback(
            "/search/multi",
            {"query": query, "page": page, "include_adult": include_adult},
        )
        movies, tv_shows, persons = [], [], []
        for item in data.get("results", []):
            mt = item.get("media_type", "")
            if mt == "movie":
                movies.append(self._parse_list([item], "movie")[0])
            elif mt == "tv":
                tv_shows.append(self._parse_list([item], "tv")[0])
            elif mt == "person":
                persons.append({
                    "id":          item.get("id"),
                    "name":        item.get("name", ""),
                    "profile_url": self._img(item.get("profile_path") or "", "w185"),
                    "known_for": [
                        kf.get("title") or kf.get("name", "")
                        for kf in item.get("known_for", [])
                    ],
                })
        return {"movies": movies, "tv": tv_shows, "persons": persons, "raw": data.get("results", [])}

    # ──────────────────────────────────────────────────────────────────
    #  多语言搜索（各语言分别搜索 + 去重合并）
    # ──────────────────────────────────────────────────────────────────

    async def search_multilang(
        self,
        query: str,
        media_type: str = "movie",
        year: int = 0,
        languages: list[str] | None = None,
    ) -> list[MetadataResult]:
        """
        以多个语言标签分别搜索，按 tmdb_id 去重后合并返回。

        与 _get_with_fallback 的区别：
          fallback  = 主语言有结果就停（优先主语言）
          multilang = 每种语言都搜，结果取并集（标题在各语言区不同时使用）

        Args:
            query:      搜索关键词
            media_type: "movie" / "tv"
            year:       年份过滤
            languages:  语言列表，默认使用 _lang_chain
        """
        langs    = languages or self._lang_chain
        is_tv    = media_type in ("tv", "series")
        endpoint = "/search/tv" if is_tv else "/search/movie"
        params: dict[str, Any] = {"query": query}
        if year:
            params["first_air_date_year" if is_tv else "year"] = year

        seen_ids: set[int]             = set()
        combined: list[MetadataResult] = []
        for lang in langs:
            data = await self._get(endpoint, params, language=lang)
            for item in data.get("results", []):
                tid = item.get("id", 0)
                if tid and tid not in seen_ids:
                    seen_ids.add(tid)
                    combined.extend(self._parse_list([item], "tv" if is_tv else "movie"))
        return combined

    # ──────────────────────────────────────────────────────────────────
    #  剧集专属：季 / 集 / 剧集组
    # ──────────────────────────────────────────────────────────────────

    async def get_tv_season(self, tmdb_id: int, season_number: int) -> dict:
        """获取剧集某季详情（含集列表）"""
        return await self._get(f"/tv/{tmdb_id}/season/{season_number}")

    async def get_tv_episode(self, tmdb_id: int, season_number: int, episode_number: int) -> dict:
        """获取剧集某集详情"""
        return await self._get(f"/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}")

    async def get_episode_groups(self, tmdb_id: int) -> list[dict]:
        """
        获取电视剧的所有剧集组列表。

        剧集组处理"播出顺序 / 绝对顺序 / DVD顺序"等多种排列方式。
        每条记录增加 type_label 字段（EPISODE_GROUP_TYPES 枚举值）。
        """
        data = await self._get(f"/tv/{tmdb_id}/episode_groups")
        results = data.get("results", [])
        for r in results:
            r["type_label"] = EPISODE_GROUP_TYPES.get(r.get("type"), "Unknown")
        return results

    async def get_episode_group_detail(self, group_id: str) -> dict:
        """
        获取指定剧集组的详情（含各子分组的 episode 列表）。

        Args:
            group_id: get_episode_groups() 返回的 id 字符串

        Returns 示例:
            {
                "id": "...", "name": "Aired Order", "type": 1,
                "type_label": "Original Air Date",
                "groups": [
                    {"id": "...", "name": "Season 1", "order": 0,
                     "episodes": [{episode_detail}, ...]}
                ]
            }
        """
        data = await self._get(f"/tv/episode_group/{group_id}")
        if data:
            data["type_label"] = EPISODE_GROUP_TYPES.get(data.get("type"), "Unknown")
        return data

    # ──────────────────────────────────────────────────────────────────
    #  外部 ID
    # ──────────────────────────────────────────────────────────────────

    async def get_external_ids(self, tmdb_id: int, media_type: str = "movie") -> dict:
        is_tv = media_type in ("tv", "series")
        return await self._get(f"/{'tv' if is_tv else 'movie'}/{tmdb_id}/external_ids")

    # ──────────────────────────────────────────────────────────────────
    #  私有解析工具
    # ──────────────────────────────────────────────────────────────────

    def _parse_list(self, items: list[dict], media_type: str) -> list[MetadataResult]:
        is_tv, out = media_type == "tv", []
        for item in items:
            release = item.get("first_air_date" if is_tv else "release_date", "") or ""
            out.append(MetadataResult(
                provider       = "tmdb",
                media_type     = media_type,
                tmdb_id        = item.get("id", 0),
                title          = item.get("name" if is_tv else "title", ""),
                original_title = item.get("original_name" if is_tv else "original_title", ""),
                year           = int(release[:4]) if len(release) >= 4 else 0,
                overview       = (item.get("overview") or "")[:300],
                poster_url     = self._img(item.get("poster_path") or ""),
                backdrop_url   = self._img(item.get("backdrop_path") or "", "w780"),
                vote_average   = item.get("vote_average", 0),
                extra          = {"id": item.get("id"), "genre_ids": item.get("genre_ids", [])},
            ))
        return out

    def _parse_detail(self, data: dict, media_type: str) -> MetadataResult:
        is_tv   = media_type == "tv"
        release = data.get("first_air_date" if is_tv else "release_date", "") or ""
        genres  = [g.get("name", "") for g in data.get("genres", [])]
        return MetadataResult(
            provider       = "tmdb",
            media_type     = media_type,
            tmdb_id        = data.get("id", 0),
            imdb_id        = data.get("imdb_id", ""),
            title          = data.get("name" if is_tv else "title", ""),
            original_title = data.get("original_name" if is_tv else "original_title", ""),
            year           = int(release[:4]) if len(release) >= 4 else 0,
            overview       = data.get("overview", ""),
            poster_url     = self._img(data.get("poster_path") or ""),
            backdrop_url   = self._img(data.get("backdrop_path") or "", "w780"),
            genres         = genres,
            vote_average   = data.get("vote_average", 0),
            extra = {
                "id":                 data.get("id"),
                "runtime":            data.get("runtime"),
                "status":             data.get("status"),
                "number_of_seasons":  data.get("number_of_seasons"),
                "number_of_episodes": data.get("number_of_episodes"),
                "networks":           [n.get("name") for n in data.get("networks", [])],
                "origin_country":     data.get("origin_country", []),
            },
        )

    @staticmethod
    def _img(path: str, size: str = "w500") -> str:
        if not path:
            return ""
        return f"{_IMAGE_BASE}/{size}{path}"