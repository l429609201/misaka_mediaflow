# src/services/redirect_service.py
# 统一 302 解析服务 — 参考 P115StrmHelper redirect_url 协议
#
# 解析优先级:
#   1. pickcode (直接)
#   2. url 中提取 pickcode
#   3. args_path (路径拼接方式)
#   4. query.path
#   5. url 中提取 path
#   6. strm_content 中提取 pickcode / path
#   7. item_id → PlaybackInfo.MediaSources.Path
#   8. item_id → Items/{id} 明细兜底

import logging
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_async_session_local
from src.db.models import MediaItem, PathMapping, SystemConfig, P115FsCache
from src.core.config import settings

logger = logging.getLogger(__name__)

# ── pick_code 提取正则（兼容多种 STRM / URL 格式）──────────────────────────
_PICK_CODE_RE = [
    re.compile(r"/p115/play/([a-zA-Z0-9]{8,})", re.IGNORECASE),          # 本项目 Go 302
    re.compile(r"[?&]pick_?code=([a-zA-Z0-9]{8,})", re.IGNORECASE),      # query pickcode / pick_code
    re.compile(r"/redirect_url/?\?.*pick_?code=([a-zA-Z0-9]{8,})", re.IGNORECASE),  # 本项目 redirect_url
    re.compile(r"/d/([a-zA-Z0-9]{8,})(?:[?/.]|$)"),                      # CMS /d/<code>
    re.compile(r"[?&]fileid=([a-zA-Z0-9]{8,})", re.IGNORECASE),          # MH fileid
    re.compile(r"[?&]id=([a-zA-Z0-9]{8,})", re.IGNORECASE),              # 通用 id
]


def _extract_pickcode_from_text(text: str) -> str:
    """从任意字符串中提取 pick_code"""
    if not text:
        return ""
    for pat in _PICK_CODE_RE:
        m = pat.search(text)
        if m:
            candidate = m.group(1)
            if candidate.isalnum() and len(candidate) >= 8:
                return candidate
    return ""


def _normalize_path(raw: str) -> str:
    """路径标准化：URL decode → 反斜杠转斜杠 → 合并重复斜杠"""
    p = unquote(raw or "").replace("\\", "/")
    while "//" in p:
        p = p.replace("//", "/")
    return p.strip()


class RedirectService:
    """统一 302 解析服务（对齐 P115StrmHelper redirect_url 协议）"""

    # ──────────────────────────────────────────────────────────────────────
    #  主入口：统一解析
    # ──────────────────────────────────────────────────────────────────────

    async def resolve_any(
        self,
        *,
        pickcode: str = "",
        pick_code: str = "",      # 兼容旧参数名
        args_path: str = "",      # /redirect_url/{args:path} 路径部分
        path: str = "",           # query ?path=
        url: str = "",            # query ?url=
        file_name: str = "",      # 兼容 P115StrmHelper ?file_name=
        share_code: str = "",     # 兼容 P115StrmHelper ?share_code=
        receive_code: str = "",   # 兼容 P115StrmHelper ?receive_code=
        item_id: str = "",        # Emby item_id（兜底）
        storage_id: int = 0,
        api_key: str = "",
        user_agent: str = "",     # 播放器真实 UA，透传给 115 downurl 接口
    ) -> dict:
        """
        统一解析入口，返回 {url, expires_in, source, error}
        source 字段标记解析来源，便于日志追踪。
        """
        # ── 1. pickcode 直接命中 ────────────────────────────────────────
        pc = (pickcode or pick_code or "").strip()
        if pc:
            logger.info("[redirect] 优先级1 pickcode=%s", pc)
            return await self._resolve_by_pickcode(pc, user_agent=user_agent, source="pickcode")

        # ── 2. url 中提取 pickcode ──────────────────────────────────────
        if url:
            extracted_pc = _extract_pickcode_from_text(url)
            if extracted_pc:
                logger.info("[redirect] 优先级2 url->pickcode=%s", extracted_pc)
                return await self._resolve_by_pickcode(extracted_pc, user_agent=user_agent, source="url_pickcode")

        # ── 3. args_path（路径拼接方式）─────────────────────────────────
        if args_path:
            normalized = _normalize_path(args_path)
            logger.info("[redirect] 优先级3 args_path=%s", normalized)
            async with get_async_session_local() as db:
                result = await self._resolve_by_path(db, normalized, storage_id, source="args_path")
            if result.get("url"):
                return result

        # ── 4. query.path ────────────────────────────────────────────────
        if path:
            normalized = _normalize_path(path)
            logger.info("[redirect] 优先级4 query.path=%s", normalized)
            async with get_async_session_local() as db:
                result = await self._resolve_by_path(db, normalized, storage_id, source="query_path")
            if result.get("url"):
                return result

        # ── 5. url 中提取路径 ────────────────────────────────────────────
        if url:
            extracted_path = self._extract_path_from_url(url)
            if extracted_path:
                logger.info("[redirect] 优先级5 url->path=%s", extracted_path)
                async with get_async_session_local() as db:
                    result = await self._resolve_by_path(db, extracted_path, storage_id, source="url_path")
                if result.get("url"):
                    return result

        # ── 6. share_code + receive_code ─────────────────────────────────
        if share_code and receive_code:
            logger.info("[redirect] 优先级6 share_code=%s", share_code)
            return {"url": "", "expires_in": 0, "source": "share",
                    "error": "share_code resolution not yet implemented"}

        # ── 7. item_id → PlaybackInfo → path ────────────────────────────
        if item_id:
            logger.info("[redirect] 优先级7 item_id=%s via PlaybackInfo", item_id)
            async with get_async_session_local() as db:
                result = await self._resolve_by_item_id(db, item_id, api_key, storage_id)
            if result.get("url"):
                return result

        return {"url": "", "expires_in": 0, "source": "none",
                "error": "no resolvable input provided"}

    # ──────────────────────────────────────────────────────────────────────
    #  解析分支
    # ──────────────────────────────────────────────────────────────────────

    async def _resolve_by_pickcode(self, pickcode: str, user_agent: str = "", source: str = "pickcode") -> dict:
        """通过 pick_code 直接获取 115 直链"""
        try:
            from src.adapters.storage.p115 import P115Manager
            manager = P115Manager()
            if not manager.enabled:
                return {"url": "", "expires_in": 0, "source": source, "error": "115 not enabled"}

            # ── 确保已初始化 ─────────────────────────────────────────────────
            if not manager.ready:
                manager.initialize()

            # ── 从数据库加载 Cookie（解决扫码后重启 Cookie 丢失问题）─────────
            if not manager.auth.has_cookie:
                await self._load_cookie_from_db(manager)

            if not manager.auth.has_cookie:
                return {"url": "", "expires_in": 0, "source": source, "error": "115 cookie not set"}

            link = await manager.adapter.get_direct_link("", pick_code=pickcode, user_agent=user_agent)
            if link and link.url:
                logger.info("[redirect] pickcode=%s 直链成功 source=%s", pickcode, source)
                return {"url": link.url, "expires_in": link.expires_in, "source": source, "error": ""}
            return {"url": "", "expires_in": 0, "source": source, "error": "empty link from 115"}
        except Exception as e:
            logger.error("[redirect] pickcode=%s 直链异常: %s", pickcode, e)
            return {"url": "", "expires_in": 0, "source": source, "error": str(e)}

    @staticmethod
    async def _load_cookie_from_db(manager) -> None:
        """从数据库加载持久化 Cookie，与 P115Service 保持一致"""
        try:
            from src.db.models.system import SystemConfig
            async with get_async_session_local() as db:
                result = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == "p115_cookie")
                )
                cfg = result.scalars().first()
                if cfg and cfg.value:
                    manager.auth.set_cookie(cfg.value)
                    logger.info("[redirect] 从数据库加载 115 Cookie 成功 (len=%d)", len(cfg.value))
        except Exception as e:
            logger.warning("[redirect] 从数据库加载 115 Cookie 失败: %s", e)

    async def _resolve_by_path(
        self, db: AsyncSession, file_path: str, storage_id: int, source: str = "path"
    ) -> dict:
        """
        通过路径解析：
        1. 先尝试从路径中提取 pickcode（STRM 内容场景）
        2. PathMapping 本地路径 → 云端路径
        3. P115FsCache 查 pickcode（精确路径）
        4. P115FsCache 查 pickcode（文件名兜底）
        5. 115 API 搜索（FsCache 无数据时直接调用网盘 API）⭐ 参考 gostrm 逻辑
        """
        # 1. 路径本身就是 STRM 文件 → 读取内容提取 pickcode
        if file_path.lower().endswith(".strm"):
            content = self._read_strm_file(file_path)
            if content:
                pc = _extract_pickcode_from_text(content)
                if pc:
                    logger.info("[redirect] STRM文件提取pickcode=%s path=%s", pc, file_path)
                    return await self._resolve_by_pickcode(pc, source=f"{source}_strm")
                # STRM 内容本身是个 URL → 递归解析
                if content.startswith("http"):
                    pc2 = _extract_pickcode_from_text(content)
                    if pc2:
                        return await self._resolve_by_pickcode(pc2, source=f"{source}_strm_url")

        # 2. PathMapping：本地挂载路径 → 云端路径
        cloud_path = await self._apply_path_mapping(db, file_path)

        # 3. P115FsCache 查 pickcode（精确路径）
        if cloud_path:
            pc = await self._lookup_pickcode_from_fscache(db, cloud_path)
            if pc:
                logger.info("[redirect] FsCache命中 cloud_path=%s → pickcode=%s", cloud_path, pc)
                return await self._resolve_by_pickcode(pc, source=f"{source}_fscache")

        # 4. 用文件名再尝试一次 FsCache
        filename = Path(file_path).name
        if filename:
            pc = await self._lookup_pickcode_by_filename(db, filename)
            if pc:
                logger.info("[redirect] 文件名命中 filename=%s → pickcode=%s", filename, pc)
                return await self._resolve_by_pickcode(pc, source=f"{source}_filename")

        # 5. ⭐ FsCache 无数据时，直接调用 115 API 搜索（对齐 gostrm handle115PanDirectLink 逻辑）
        #    前提：必须有 cloud_path（PathMapping 转换成功），才能确定文件在网盘中的位置
        if cloud_path:
            logger.info(
                "[redirect] FsCache未命中，尝试直接调用 115 API 搜索: cloud_path=%s", cloud_path
            )
            pc = await self._search_115_by_cloud_path(cloud_path, source)
            if pc:
                return await self._resolve_by_pickcode(pc, source=f"{source}_api_search")

        logger.warning("[redirect] 路径解析失败 path=%s cloud=%s", file_path, cloud_path)
        return {"url": "", "expires_in": 0, "source": source, "error": "path not resolved"}

    async def _resolve_by_item_id(
        self, db: AsyncSession, item_id: str, api_key: str, storage_id: int
    ) -> dict:
        """通过 item_id 解析（兜底链路，兼容旧逻辑）"""
        # 7a. 查本地 MediaItem
        result = await db.execute(select(MediaItem).where(MediaItem.item_id == item_id))
        media = result.scalars().first()
        if media:
            if media.pick_code:
                return await self._resolve_by_pickcode(media.pick_code, source="mediaitem_pickcode")
            if media.file_path:
                r = await self._resolve_by_path(db, media.file_path, storage_id, source="mediaitem_path")
                if r.get("url"):
                    return r

        # 7b. Emby PlaybackInfo → MediaSources.Path
        host, stored_api_key = await self._get_media_server_config(db)
        used_api_key = api_key or stored_api_key
        if host and used_api_key:
            path = await self._fetch_playback_path(host, used_api_key, item_id)
            if path:
                logger.info("[redirect] PlaybackInfo path=%s item_id=%s", path, item_id)
                r = await self._resolve_by_path(db, path, storage_id, source="playback_info")
                if r.get("url"):
                    # 缓存成功结果
                    await self._cache_item_mapping(db, item_id, path, r.get("_pickcode", ""))
                    return r

            # 7c. Items/{id} 明细兜底
            item_info = await self._fetch_emby_item(host, used_api_key, item_id)
            if item_info:
                path = self._extract_file_path(item_info)
                if path:
                    logger.info("[redirect] Items明细 path=%s item_id=%s", path, item_id)
                    r = await self._resolve_by_path(db, path, storage_id, source="item_detail")
                    if r.get("url"):
                        await self._cache_item_mapping(db, item_id, path, r.get("_pickcode", ""))
                        return r

        return {"url": "", "expires_in": 0, "source": "item_id", "error": "item not resolvable"}

    # ──────────────────────────────────────────────────────────────────────
    #  辅助：URL 解析
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_path_from_url(url: str) -> str:
        """从 HTTP URL 中提取路径部分作为 path 输入"""
        try:
            parsed = urlparse(url)
            # 先看 query 里有没有 path=
            qs = parse_qs(parsed.query)
            if "path" in qs:
                return _normalize_path(qs["path"][0])
            # 否则取 URL path 本身（去掉已知前缀）
            p = _normalize_path(parsed.path)
            for prefix in ("/redirect_url", "/p115/play"):
                if p.startswith(prefix):
                    p = p[len(prefix):]
                    break
            return p.strip("/")
        except Exception:
            return ""

    # ──────────────────────────────────────────────────────────────────────
    #  辅助：路径映射
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    async def _apply_path_mapping(db: AsyncSession, local_path: str) -> str:
        """PathMapping：local_path → cloud_path（仅启用的映射，按优先级降序匹配）"""
        rows = await db.execute(
            select(PathMapping)
            .where(PathMapping.is_active == 1)
            .order_by(PathMapping.priority.desc())
        )
        mappings = rows.scalars().all()
        norm = _normalize_path(local_path)
        for m in mappings:
            local_prefix = _normalize_path(m.local_prefix or "")
            cloud_prefix = _normalize_path(m.cloud_prefix or "")
            if not local_prefix or not cloud_prefix:
                continue
            if norm.startswith(local_prefix):
                suffix = norm[len(local_prefix):]
                cloud_path = cloud_prefix + suffix
                logger.debug(
                    "[redirect] PathMapping 命中: %s → %s (storage_id=%s, priority=%s)",
                    local_path, cloud_path, m.storage_id, m.priority,
                )
                return cloud_path
        logger.debug("[redirect] PathMapping 无匹配: %s", local_path)
        return ""

    @staticmethod
    async def _lookup_pickcode_from_fscache(db: AsyncSession, cloud_path: str) -> str:
        """按云端路径精确匹配 P115FsCache"""
        try:
            row = await db.execute(
                select(P115FsCache).where(P115FsCache.local_path == cloud_path)
            )
            item = row.scalars().first()
            if item and item.pick_code:
                return item.pick_code
        except Exception as e:
            logger.debug("[redirect] FsCache查询异常: %s", e)
        return ""

    @staticmethod
    async def _lookup_pickcode_by_filename(db: AsyncSession, filename: str) -> str:
        """按文件名匹配 P115FsCache（模糊兜底）"""
        try:
            row = await db.execute(
                select(P115FsCache).where(P115FsCache.name == filename)
            )
            item = row.scalars().first()
            if item and item.pick_code:
                return item.pick_code
        except Exception as e:
            logger.debug("[redirect] 文件名FsCache查询异常: %s", e)
        return ""

    async def _search_115_by_cloud_path(self, cloud_path: str, source: str) -> str:
        """
        ⭐ FsCache 无数据时的终极兜底：直接调用 115 API 搜索文件获取 pickcode。

        对齐参考项目 gostrm 的 handle115PanDirectLink 逻辑：
          - 参考项目用 pathParser 提取 relativePath，然后直接查 115 API
          - 本项目通过 PathMapping 得到 cloud_path（等价于 relativePath）
          - 用 cloud_path 的文件名调用 115 搜索接口，精确匹配文件名后返回 pick_code

        搜索成功后 pick_code 会被上层 _resolve_by_pickcode 转换为 CDN 直链。
        """
        try:
            from src.adapters.storage.p115 import P115Manager
            manager = P115Manager()
            if not manager.enabled:
                logger.debug("[redirect] 115 未启用，跳过 API 搜索")
                return ""

            if not manager.ready:
                manager.initialize()

            if not manager.auth.has_cookie:
                await self._load_cookie_from_db(manager)

            if not manager.auth.has_cookie:
                logger.warning("[redirect] 115 Cookie 未设置，无法执行 API 搜索")
                return ""

            pc = await manager.adapter.search_file_by_cloud_path(cloud_path)
            if pc:
                logger.info(
                    "[redirect] ⭐ 115 API 搜索成功: cloud_path=%s → pickcode=%s (source=%s)",
                    cloud_path, pc, source,
                )
            return pc
        except Exception as e:
            logger.error("[redirect] 115 API 搜索异常: %s (cloud_path=%s)", e, cloud_path)
            return ""

    # ──────────────────────────────────────────────────────────────────────
    #  辅助：媒体服务器
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    async def _get_media_server_config(db: AsyncSession) -> tuple:
        """从数据库读取媒体服务器配置"""
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
        return (host or "").rstrip("/"), api_key or ""

    @staticmethod
    async def _fetch_playback_path(host: str, api_key: str, item_id: str) -> str:
        """调用 Emby PlaybackInfo 获取 MediaSources.Path（比 Items/{id} 更可靠）"""
        import httpx
        url = f"{host}/emby/Items/{item_id}/PlaybackInfo"
        masked_key = api_key[:4] + "****" if len(api_key) > 4 else "****"
        logger.debug("[redirect] _fetch_playback_path → POST %s?api_key=%s", url, masked_key)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url,
                    params={"api_key": api_key},
                    json={"DeviceProfile": {}},
                )
                logger.debug("[redirect] _fetch_playback_path ← HTTP %d item_id=%s", resp.status_code, item_id)
                if resp.status_code == 200:
                    data = resp.json()
                    sources = data.get("MediaSources", [])
                    for src in sources:
                        p = src.get("Path", "")
                        if p:
                            logger.debug("[redirect] _fetch_playback_path 拿到路径: %s", p)
                            return p
        except Exception as e:
            logger.debug("[redirect] PlaybackInfo异常 item_id=%s: %s", item_id, e)
        return ""

    @staticmethod
    async def _fetch_emby_item(host: str, api_key: str, item_id: str) -> dict | None:
        """调用 Emby Items/{id} 明细接口（兜底）"""
        import httpx
        import urllib.parse
        params = {"api_key": api_key, "Fields": "Path,MediaSources"}
        masked_key = api_key[:4] + "****" if len(api_key) > 4 else "****"
        debug_qs = urllib.parse.urlencode({**params, "api_key": masked_key})
        logger.debug("[redirect] _fetch_emby_item → GET %s/emby/Items/%s?%s", host, item_id, debug_qs)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{host}/emby/Items/{item_id}",
                    params=params,
                )
                logger.debug(
                    "[redirect] _fetch_emby_item ← HTTP %d item_id=%s body_preview=%s",
                    resp.status_code, item_id,
                    resp.text[:200] if resp.status_code != 200 else "(ok)",
                )
                if resp.status_code == 200:
                    return resp.json()
                logger.warning("[redirect] Emby Items返回%d item_id=%s", resp.status_code, item_id)
        except Exception as e:
            logger.debug("[redirect] Emby Items异常 item_id=%s: %s", item_id, e)
        return None

    @staticmethod
    def _extract_file_path(item_info: dict) -> str:
        """从 Emby 条目中提取文件路径"""
        sources = item_info.get("MediaSources", [])
        if sources:
            p = sources[0].get("Path", "")
            if p:
                return p
        return item_info.get("Path", "")

    @staticmethod
    def _read_strm_file(file_path: str) -> str:
        """读取 STRM 文件内容"""
        try:
            p = Path(file_path)
            if p.exists() and p.is_file():
                return p.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.debug("[redirect] 读取STRM失败 %s: %s", file_path, e)
        return ""

    @staticmethod
    async def _cache_item_mapping(db: AsyncSession, item_id: str, file_path: str, pick_code: str):
        """将 item_id → pick_code 缓存到 MediaItem 表"""
        try:
            row = await db.execute(select(MediaItem).where(MediaItem.item_id == item_id))
            if not row.scalars().first():
                db.add(MediaItem(item_id=item_id, file_path=file_path, pick_code=pick_code))
                await db.commit()
        except Exception as e:
            logger.debug("[redirect] 缓存MediaItem失败: %s", e)
            await db.rollback()

