# src/services/metadata_service.py
# 统一元数据服务层
#
# 职责：
#   · 从 SystemConfig 读取各 Provider 配置，通过 MetadataFactory 创建实例
#   · 带进程级缓存（避免每次请求重新实例化）
#   · 暴露统一接口供上层服务调用（classify_engine / scrape 等）
#   · 配置更新时通过 invalidate_cache() 刷新
#
# 调用方只需：
#   from src.services.metadata_service import metadata_service
#
#   ok   = await metadata_service.is_provider_available('tmdb')
#   info = await metadata_service.fetch_classify_info('进击的巨人', False, '2013')

import json
import logging
from typing import Optional

from sqlalchemy import select

from src.adapters.metadata.base import MetadataProvider, MetadataResult
from src.adapters.metadata.factory import MetadataFactory
from src.db import get_async_session_local
from src.db.models.system import SystemConfig

logger = logging.getLogger(__name__)

# 进程级 provider 实例缓存 { provider_name: MetadataProvider | None }
_provider_cache: dict[str, Optional[MetadataProvider]] = {}

# 查询结果内存缓存 { "title|movie/tv": {genre_ids, origin_country, original_language} }
_classify_cache: dict[str, dict] = {}


class MetadataService:
    """
    统一元数据服务层。

    所有需要元数据查询的服务（classify_engine、刮削等）
    统一通过此服务调用，不直接接触具体 Provider 实现。
    """

    # ── Provider 实例管理 ──────────────────────────────────────────────────────

    async def get_provider(self, name: str) -> Optional[MetadataProvider]:
        """
        获取已配置的 Provider 实例（带进程级缓存）。

        从 SystemConfig 读取对应配置，通过 MetadataFactory 创建实例。
        配置不存在或 API Key 为空时返回 None。

        Args:
            name: Provider 名称，如 'tmdb'
        """
        if name in _provider_cache:
            return _provider_cache[name]

        provider = await self._build_provider(name)
        _provider_cache[name] = provider
        return provider

    async def _build_provider(self, name: str) -> Optional[MetadataProvider]:
        """从 SystemConfig 读配置并通过工厂创建 Provider 实例。

        读取顺序：
        1. provider_cls.CONFIG_KEY 专属 key（如 metadata_tmdb）
        2. search_source_override[name]（搜索源页面保存的字段值）
        两者合并，专属 key 优先。
        """
        provider_cls = MetadataFactory.get_provider_class(name)
        if provider_cls is None:
            logger.debug("[MetadataService] 未知 Provider: %s", name)
            return None

        config_key = provider_cls.CONFIG_KEY
        if not config_key:
            logger.debug("[MetadataService] Provider %s 未声明 CONFIG_KEY", name)
            return None

        try:
            async with get_async_session_local() as db:
                # 1. 读专属 key
                row = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == config_key)
                )
                cfg_row = row.scalars().first()
                cfg_data: dict = {}
                if cfg_row and cfg_row.value:
                    cfg_data = json.loads(cfg_row.value)

                # 2. 读搜索源页面保存的 override（search_source_override）
                override_row = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == "search_source_override")
                )
                override_cfg = override_row.scalars().first()
                if override_cfg and override_cfg.value:
                    override_map: dict = json.loads(override_cfg.value)
                    source_vals: dict = override_map.get(name, {})
                    # 合并：专属 key 优先，搜索源作为补充
                    cfg_data = {**source_vals, **cfg_data}

            # cfg_data 为空也允许通过（有些 Provider 不需要配置，如 IMDB）
            # 只有声明了 required 字段且未填写时才拦截

            # 检查必填字段（CONFIG_FIELDS 中 required=True 的字段）
            for field_spec in provider_cls.CONFIG_FIELDS:
                if field_spec.required and not cfg_data.get(field_spec.key, "").strip():
                    logger.debug(
                        "[MetadataService] Provider %s 缺少必填字段: %s", name, field_spec.key
                    )
                    return None

            # 只传 __init__ 支持的参数，过滤掉多余字段（如 api_url / image_url）
            import inspect as _inspect
            valid_keys = set(_inspect.signature(provider_cls.__init__).parameters) - {"self"}
            filtered = {k: v for k, v in cfg_data.items() if k in valid_keys}

            # 通过工厂创建实例，配置通过 kwargs 注入
            provider = MetadataFactory.create(name, **filtered)
            if not provider.available:
                logger.debug("[MetadataService] Provider %s 不可用（available=False）", name)
                return None

            logger.info("[MetadataService] Provider 已初始化: %s", name)
            return provider

        except Exception as e:
            logger.warning("[MetadataService] 初始化 Provider %s 失败: %s", name, e)
            return None

    async def is_provider_available(self, name: str) -> bool:
        """检查指定 Provider 是否已配置且可用。"""
        return (await self.get_provider(name)) is not None

    async def get_enabled_provider_names(self) -> list[str]:
        """获取所有已启用的搜索源名称列表（按 discover 顺序）"""
        from src.adapters.metadata.factory import MetadataFactory
        all_providers = MetadataFactory.list_providers()

        async with get_async_session_local() as db:
            row = await db.execute(
                select(SystemConfig).where(SystemConfig.key == "search_source_enabled")
            )
            cfg = row.scalars().first()
            enabled_map = {}
            if cfg and cfg.value:
                enabled_map = json.loads(cfg.value)

        names = []
        for p in all_providers:
            name = p["name"]
            if enabled_map.get(name, True):  # 默认启用
                names.append(name)
        return names

    async def get_tv_seasons_dynamic(self, provider_ids: dict) -> tuple[dict | None, str]:
        """
        根据已启用的搜索源动态获取剧集季/集信息。

        按优先级尝试各 Provider 的 get_tv_seasons()，返回第一个有结果的。

        Args:
            provider_ids: {"tmdb": 12345, "tvdb": 67890, "bgm": 111, ...}

        Returns:
            (tv_detail_dict, provider_name) 或 (None, "")
        """
        # provider name → provider_ids 中对应的 ID key
        id_mapping = {
            "tmdb": "tmdb",
            "tvdb": "tvdb",
            "bangumi": "bgm",
        }

        enabled = await self.get_enabled_provider_names()
        for pname in enabled:
            id_key = id_mapping.get(pname)
            if not id_key:
                continue
            media_id = provider_ids.get(id_key)
            if not media_id:
                continue
            provider = await self.get_provider(pname)
            if not provider:
                continue
            try:
                result = await provider.get_tv_seasons(media_id)
                if result and result.get("seasons"):
                    logger.info("[MetadataService] get_tv_seasons 成功: %s (id=%s)", pname, media_id)
                    return result, pname
            except Exception as e:
                logger.debug("[MetadataService] %s.get_tv_seasons 失败: %s", pname, e)
        return None, ""

    def invalidate_cache(self, name: str = None) -> None:
        """
        清除 Provider 实例缓存（配置更新后调用）。
        name=None 时清除全部缓存。
        """
        global _provider_cache, _classify_cache
        if name:
            _provider_cache.pop(name, None)
            logger.info("[MetadataService] 已清除 Provider 缓存: %s", name)
        else:
            _provider_cache.clear()
            _classify_cache.clear()
            logger.info("[MetadataService] 已清除全部缓存")

    # ── 分类引擎专用接口 ───────────────────────────────────────────────────────

    async def fetch_classify_info(
        self,
        title: str,
        is_movie: bool,
        year: Optional[str] = None,
        provider_name: str = "tmdb",
    ) -> dict:
        """
        为分类引擎提供元数据查询，返回可用于规则匹配的字段。

        返回格式：
        {
            "genre_ids":         [16, 10751],
            "origin_country":    ["JP"],
            "original_language": "ja",
        }
        查询失败或 Provider 未配置时返回 {}。

        结果带进程级内存缓存，相同 title+类型 不重复请求。
        """
        cache_key = f"{provider_name}|{title}|{'movie' if is_movie else 'tv'}"
        if cache_key in _classify_cache:
            return _classify_cache[cache_key]

        result: dict = {}
        provider = await self.get_provider(provider_name)
        if provider is None:
            return result

        try:
            media_type = "movie" if is_movie else "tv"
            year_int   = int(year) if year and str(year).isdigit() else 0

            # 搜索（带年份 → 无年份回退）
            results = await provider.search(title, media_type=media_type, year=year_int)
            if not results and year_int:
                results = await provider.search(title, media_type=media_type)

            if results:
                top      = results[0]
                media_id = top.extra.get("id") or top.tmdb_id
                if media_id:
                    detail = await provider.get_detail(int(media_id), media_type=media_type)
                    if detail:
                        result = {
                            "genre_ids":         top.extra.get("genre_ids", []),
                            "origin_country":    detail.extra.get("origin_country", []),
                            "original_language": detail.extra.get("original_language", ""),
                        }

        except Exception as e:
            logger.warning(
                "[MetadataService] fetch_classify_info 失败 title=%s provider=%s: %s",
                title, provider_name, e,
            )

        _classify_cache[cache_key] = result
        return result

    # ── 通用查询接口（供其他服务使用）────────────────────────────────────────

    async def search(
        self,
        title: str,
        media_type: str = "movie",
        year: int = 0,
        provider_name: str = "tmdb",
    ) -> list[MetadataResult]:
        """通用搜索接口。"""
        provider = await self.get_provider(provider_name)
        if provider is None:
            return []
        try:
            return await provider.search(title, media_type=media_type, year=year)
        except Exception as e:
            logger.warning("[MetadataService] search 失败: %s", e)
            return []

    async def get_detail(
        self,
        media_id: int | str,
        media_type: str = "movie",
        provider_name: str = "tmdb",
    ) -> Optional[MetadataResult]:
        """通用详情查询接口。"""
        provider = await self.get_provider(provider_name)
        if provider is None:
            return None
        try:
            return await provider.get_detail(media_id, media_type=media_type)
        except Exception as e:
            logger.warning("[MetadataService] get_detail 失败: %s", e)
            return None

    async def list_available_providers(self) -> list[dict]:
        """
        返回所有已注册 Provider 的可用状态（供前端显示）。
        [{"name": "tmdb", "label": "TMDB", "available": true}, ...]
        """
        all_providers = MetadataFactory.list_providers()
        result = []
        for p in all_providers:
            available = await self.is_provider_available(p["name"])
            result.append({
                "name":      p["name"],
                "label":     p["label"],
                "available": available,
                "config_key": p["config_key"],
            })
        return result


# ── 单例 ──────────────────────────────────────────────────────────────────────
metadata_service = MetadataService()

