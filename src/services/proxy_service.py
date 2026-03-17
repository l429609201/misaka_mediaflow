# app/services/proxy_service.py
# 302 反代业务逻辑 — 供 Go 内部 API 调用
#
# 解析优先级:
#   1. MediaItem 缓存 (pick_code / file_path)
#   2. Emby API fallback → STRM 文件提取 pick_code
#   3. Emby API fallback → 路径映射 → P115FsCache 查 pick_code
#
# 参考实现:
#   - emby-toolkit:       万能 STRM pick_code 提取器 + media_db 查找
#   - p115strmhelper:     get_pickcode_by_path (数据库 + 115 API)

import json
import logging
import re
from pathlib import Path, PurePosixPath  # noqa: F401 — PurePosixPath used in method

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_async_session_local
from src.db.models import MediaItem, StorageConfig, PathMapping, SystemConfig
from src.db.models import P115FsCache
from src.core.config import settings

logger = logging.getLogger(__name__)

# ---- 万能 pick_code 提取正则 ----
# 参考 emby-toolkit 的 extract_pickcode_from_strm_url，支持多种 STRM 格式
_PICK_CODE_PATTERNS = [
    # 1. ETK / 本项目格式: /p115/play/<pick_code>/
    re.compile(r"/p115/play/([a-zA-Z0-9]+)"),
    # 2. MP 格式: pick_code=xxx 或 pickcode=xxx
    re.compile(r"pick_?code=([a-zA-Z0-9]+)", re.IGNORECASE),
    # 3. CMS 格式: /d/<pick_code>
    re.compile(r"/d/([a-zA-Z0-9]+)(?:[.?/]|$)"),
    # 4. MH 格式: fileid=xxx
    re.compile(r"fileid=([a-zA-Z0-9]+)", re.IGNORECASE),
]


class ProxyService:
    """302 反代业务逻辑"""

    async def resolve_direct_link(
        self, item_id: str, storage_id: int = 0, api_key: str = "", user_id: str = ""
    ) -> dict:
        """
        解析媒体条目直链
        1. 查询 mediaitem 获取文件路径和 pick_code
        2. 如果有 pick_code → 直接走 115 直链
        3. 否则匹配 pathmapping 转换为云端路径 → 调用存储适配器
        4. ⭐ Fallback: MediaItem 不存在时，调 Emby API 获取文件路径 → 解析直链
        """
        logger.info("resolve_direct_link: item_id=%s, storage_id=%d, user_id=%s", item_id, storage_id, user_id or "N/A")

        async with get_async_session_local() as db:
            # 1. 查询媒体条目
            result = await db.execute(
                select(MediaItem).where(MediaItem.item_id == item_id)
            )
            media = result.scalars().first()

            if media:
                # 2. 如果有 pick_code → 直走 115
                if media.pick_code:
                    return await self._resolve_via_115(media.pick_code)

                # 3. 通过路径映射解析
                file_path = media.file_path
                if not file_path:
                    return {"url": "", "expires_in": 0, "error": "no file path"}
                return await self._resolve_via_path_mapping(db, file_path, storage_id)

            # ⭐ 4. MediaItem 不存在 → Fallback: 通过 Emby API 获取文件信息
            logger.info("MediaItem 不存在, 尝试 Emby API fallback: item_id=%s", item_id)
            return await self._fallback_via_emby(db, item_id, api_key, user_id, storage_id)

    # ------------------------------------------------------------------
    #  核心解析方法
    # ------------------------------------------------------------------

    async def _resolve_via_115(self, pick_code: str) -> dict:
        """通过 115 pick_code 直接获取直链"""
        try:
            from src.adapters.storage.p115 import P115Manager
            manager = P115Manager()
            if not manager.enabled:
                return {"url": "", "expires_in": 0, "error": "115 not enabled"}
            link = await manager.adapter.get_download_url(pick_code)
            if link.url:
                return {"url": link.url, "expires_in": link.expires_in}
            return {"url": "", "expires_in": 0, "error": "115 link failed"}
        except Exception as e:
            logger.error("115 直链解析异常: %s", e)
            return {"url": "", "expires_in": 0, "error": str(e)}

    async def _resolve_via_path_mapping(
        self, db: AsyncSession, file_path: str, storage_id: int
    ) -> dict:
        """通过路径映射 + 存储适配器获取直链"""
        # 查找匹配的路径映射
        query = select(PathMapping).where(PathMapping.is_active == 1)
        if storage_id > 0:
            query = query.where(PathMapping.storage_id == storage_id)
        query = query.order_by(PathMapping.priority.desc())
        result = await db.execute(query)
        mappings = result.scalars().all()

        cloud_path = ""
        matched_storage_id = 0
        for mapping in mappings:
            if file_path.startswith(mapping.local_prefix):
                cloud_path = file_path.replace(mapping.local_prefix, mapping.cloud_prefix, 1)
                matched_storage_id = mapping.storage_id
                break

        if not cloud_path:
            logger.warning("无匹配路径映射: %s", file_path)
            return {"url": "", "expires_in": 0, "error": "no path mapping"}

        # 查找存储源配置
        result = await db.execute(
            select(StorageConfig).where(StorageConfig.id == matched_storage_id)
        )
        storage = result.scalars().first()
        if not storage or storage.is_active != 1:
            return {"url": "", "expires_in": 0, "error": "storage not found or disabled"}

        # 如果是 115 存储 → 从 P115FsCache 查 pick_code 并获取直链
        if storage.type == "p115":
            return await self._resolve_115_by_cloud_path(cloud_path, db)

        # 其他存储类型 → 通用适配器
        try:
            config = json.loads(storage.config) if storage.config else {}
            from src.adapters.storage.factory import StorageFactory
            adapter = StorageFactory.create(storage.type, host=storage.host, **config)
            link = await adapter.get_direct_link(cloud_path)
            if link.url:
                return {"url": link.url, "expires_in": link.expires_in}
            return {"url": "", "expires_in": 0, "error": "adapter returned empty url"}
        except Exception as e:
            logger.error("存储适配器异常: %s", e)
            return {"url": "", "expires_in": 0, "error": str(e)}

    async def _resolve_115_by_cloud_path(
        self, cloud_path: str, db: AsyncSession | None = None
    ) -> dict:
        """
        通过云端路径查找 115 pick_code 并获取直链。
        参考 p115strmhelper 的 get_pickcode_by_path:
          1. 先查 P115FsCache 数据库（按文件名匹配）
          2. 找到 pick_code → 获取直链
        """
        try:
            from src.adapters.storage.p115 import P115Manager
            manager = P115Manager()
            if not manager.enabled:
                return {"url": "", "expires_in": 0, "error": "115 not enabled"}

            # ---- 步骤 1: 从 P115FsCache 数据库查找 pick_code ----
            pick_code = await self._lookup_pickcode_from_fscache(cloud_path, db)
            if pick_code:
                logger.info("P115FsCache 命中: cloud_path=%s → pick_code=%s", cloud_path, pick_code)
                return await self._resolve_via_115(pick_code)

            # ---- 步骤 2: 内存缓存兜底 ----
            file_id = manager.id_path_cache.get_id(cloud_path)
            if file_id:
                logger.debug("内存缓存命中 file_id=%s, 但无法转换为 pick_code", file_id)

            logger.warning("115 云端路径无法解析 pick_code: %s", cloud_path)
            return {"url": "", "expires_in": 0, "error": "115 path resolve failed"}
        except Exception as e:
            logger.error("115 路径解析异常: %s", e)
            return {"url": "", "expires_in": 0, "error": str(e)}

    async def _lookup_pickcode_from_fscache(
        self, cloud_path: str, db: AsyncSession | None = None
    ) -> str:
        """
        从 P115FsCache 表查找 pick_code。
        策略:
          1. 精确匹配 local_path（完整路径）
          2. 按文件名 + 父目录名匹配（更宽松）
          3. 仅按文件名匹配（最宽松，可能多结果取第一个）
        """
        async def _query(session: AsyncSession) -> str:
            # 提取文件名
            p = PurePosixPath(cloud_path)
            file_name = p.name

            if not file_name:
                return ""

            # 策略 1: 精确匹配 local_path
            result = await session.execute(
                select(P115FsCache.pick_code).where(
                    P115FsCache.local_path == cloud_path,
                    P115FsCache.pick_code != "",
                    P115FsCache.is_dir == 0,
                )
            )
            pc = result.scalar()
            if pc:
                return pc

            # 策略 2: 按文件名精确匹配（可能有多个同名文件，取第一个有 pick_code 的）
            result = await session.execute(
                select(P115FsCache.pick_code).where(
                    P115FsCache.name == file_name,
                    P115FsCache.pick_code != "",
                    P115FsCache.is_dir == 0,
                ).limit(1)
            )
            pc = result.scalar()
            if pc:
                return pc

            return ""

        if db:
            return await _query(db)
        async with get_async_session_local() as session:
            return await _query(session)

    # ------------------------------------------------------------------
    #  ⭐ Emby API Fallback — MediaItem 不存在时通过 Emby 获取文件信息
    # ------------------------------------------------------------------

    async def _fallback_via_emby(
        self, db: AsyncSession, item_id: str, api_key: str, user_id: str, storage_id: int
    ) -> dict:
        """
        当 MediaItem 表中没有记录时，通过 Emby/Jellyfin API 获取文件路径，
        然后根据路径类型（STRM / 普通视频）解析直链。
        """
        # 1. 获取媒体服务器配置
        ms_host, ms_api_key = await self._get_media_server_config(db)
        # 优先使用 Go 传来的 api_key
        effective_api_key = api_key or ms_api_key
        if not ms_host or not effective_api_key:
            logger.warning("媒体服务器未配置, 无法 fallback: item_id=%s", item_id)
            return {"url": "", "expires_in": 0, "error": "media server not configured"}

        # 2. 调 Emby API 获取条目详情（带 user_id）
        item_info = await self._fetch_emby_item(ms_host, effective_api_key, item_id, user_id)
        if not item_info:
            logger.warning("Emby API 未返回条目信息: item_id=%s", item_id)
            return {"url": "", "expires_in": 0, "error": "emby item not found"}

        # 3. 提取文件路径
        file_path = self._extract_file_path(item_info)
        if not file_path:
            logger.warning("Emby 条目无文件路径: item_id=%s", item_id)
            return {"url": "", "expires_in": 0, "error": "no file path in emby item"}

        logger.info("Emby fallback 获取到路径: item_id=%s, path=%s", item_id, file_path)

        # 4. 判断是否是 STRM 文件
        if file_path.lower().endswith(".strm"):
            result = await self._resolve_strm_fallback(db, item_id, item_info, file_path)
            if result and result.get("url"):
                return result

        # 5. 非 STRM 或 STRM 解析失败 → 通过路径映射
        return await self._resolve_via_path_mapping(db, file_path, storage_id)

    async def _resolve_strm_fallback(
        self, db: AsyncSession, item_id: str, item_info: dict, strm_path: str
    ) -> dict | None:
        """
        STRM 文件 fallback:
        1. 读取 STRM 文件内容
        2. 从内容中提取 pick_code
        3. 获取 115 直链
        4. 缓存 item_id → pick_code 映射
        """
        # 尝试读取 STRM 文件
        strm_content = self._read_strm_file(strm_path)
        if not strm_content:
            logger.debug("无法读取 STRM 文件: %s", strm_path)
            return None

        # 从 STRM 内容提取 pick_code
        pick_code = self._extract_pick_code(strm_content)
        if not pick_code:
            logger.debug("STRM 内容中无 pick_code: %s", strm_content[:200])
            return None

        logger.info("从 STRM 提取到 pick_code: item_id=%s, pick_code=%s", item_id, pick_code)

        # 获取 115 直链
        result = await self._resolve_via_115(pick_code)

        # 如果成功，缓存映射到 MediaItem 表
        if result.get("url"):
            await self._cache_media_mapping(db, item_id, item_info, pick_code, strm_path)

        return result

    # ------------------------------------------------------------------
    #  辅助方法
    # ------------------------------------------------------------------

    async def _get_media_server_config(self, db: AsyncSession) -> tuple:
        """获取媒体服务器配置 (host, api_key)，优先从数据库读取"""
        host = settings.media_server.host
        api_key = settings.media_server.api_key

        for key, attr in [("media_server_host", "host"), ("media_server_api_key", "api_key")]:
            row = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
            cfg = row.scalars().first()
            if cfg and cfg.value:
                val = cfg.value.strip().strip('"')
                if attr == "host":
                    host = val
                else:
                    api_key = val

        return host.rstrip("/") if host else "", api_key or ""

    async def _fetch_emby_item(self, host: str, api_key: str, item_id: str, user_id: str = "") -> dict | None:
        """调用 Emby/Jellyfin API 获取条目详情（必须带 UserId，否则 Emby 返回 404）"""
        import httpx
        params = {
            "api_key": api_key,
            "Fields": "Path,MediaSources",
        }
        if user_id:
            params["UserId"] = user_id

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{host}/emby/Items/{item_id}",
                    params=params,
                )
                if resp.status_code == 200:
                    return resp.json()
                logger.warning("Emby API 返回 %d: item_id=%s user_id=%s", resp.status_code, item_id, user_id or "N/A")
                return None
        except Exception as e:
            logger.error("调用 Emby API 异常: %s", e)
            return None

    @staticmethod
    def _extract_file_path(item_info: dict) -> str:
        """从 Emby 条目信息中提取文件路径"""
        # 优先从 MediaSources 中提取
        media_sources = item_info.get("MediaSources", [])
        if media_sources:
            path = media_sources[0].get("Path", "")
            if path:
                return path
        # 回退到顶层 Path
        return item_info.get("Path", "")

    @staticmethod
    def _extract_pick_code(content: str) -> str:
        """
        万能 pick_code 提取器（参考 emby-toolkit）。
        支持多种 STRM URL 格式:
          - /p115/play/<pick_code>/  (ETK / 本项目)
          - pick_code=xxx / pickcode=xxx  (MoviePilot)
          - /d/<pick_code>  (CMS)
          - fileid=xxx  (MH)
        """
        if not content:
            return ""
        for pattern in _PICK_CODE_PATTERNS:
            match = pattern.search(content)
            if match:
                candidate = match.group(1)
                # pick_code 通常是 17 位字母数字, 但也有例外, 只要 >=8 位就认可
                if len(candidate) >= 8 and candidate.isalnum():
                    return candidate
        return ""

    @staticmethod
    def _read_strm_file(file_path: str) -> str:
        """读取 STRM 文件内容"""
        try:
            p = Path(file_path)
            if p.exists() and p.is_file():
                content = p.read_text(encoding="utf-8").strip()
                return content
        except Exception as e:
            logger.debug("读取 STRM 文件失败 %s: %s", file_path, e)
        return ""

    async def _cache_media_mapping(
        self, db: AsyncSession, item_id: str, item_info: dict,
        pick_code: str, file_path: str
    ):
        """将 item_id → pick_code 映射缓存到 MediaItem 表"""
        try:
            media = MediaItem(
                item_id=item_id,
                title=item_info.get("Name", ""),
                item_type=item_info.get("Type", "Video"),
                file_path=file_path,
                pick_code=pick_code,
            )
            db.add(media)
            await db.commit()
            logger.info("已缓存媒体映射: item_id=%s → pick_code=%s", item_id, pick_code)
        except Exception as e:
            logger.warning("缓存媒体映射失败: %s", e)
            await db.rollback()

