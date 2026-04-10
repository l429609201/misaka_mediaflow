# src/services/subtitle_download_service.py
# 字幕自动下载服务 — OpenSubtitles API
#
# 功能：
#   1. 通过 OpenSubtitles REST API 搜索字幕
#   2. 按文件名/IMDB ID/TMDB ID 匹配最佳字幕
#   3. 下载 .srt/.ass 字幕文件到 STRM 同目录
#   4. STRM 生成后自动触发字幕下载
#
# 配置存 SystemConfig 表，key = "subtitle_download_config"

import json
import logging
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_OS_API = "https://api.opensubtitles.com/api/v1"
_cfg_cache: dict = {}
_cfg_cache_at: float = 0.0


async def _load_config() -> dict:
    global _cfg_cache, _cfg_cache_at
    if _cfg_cache and time.monotonic() - _cfg_cache_at < 60:
        return _cfg_cache
    try:
        from src.db import get_async_session_local
        from src.db.models import SystemConfig
        from sqlalchemy import select
        async with get_async_session_local() as db:
            row = await db.execute(select(SystemConfig).where(
                SystemConfig.key == "subtitle_download_config"))
            cfg = row.scalars().first()
            if cfg and cfg.value:
                _cfg_cache = json.loads(cfg.value)
                _cfg_cache_at = time.monotonic()
                return _cfg_cache
    except Exception as e:
        logger.debug("[SubDL] 配置加载失败: %s", e)
    return _cfg_cache or {}


async def save_config(config: dict) -> bool:
    global _cfg_cache, _cfg_cache_at
    try:
        from src.db import get_async_session_local
        from src.db.models import SystemConfig
        from sqlalchemy import select
        async with get_async_session_local() as db:
            row = await db.execute(select(SystemConfig).where(
                SystemConfig.key == "subtitle_download_config"))
            obj = row.scalars().first()
            val = json.dumps(config, ensure_ascii=False)
            if obj:
                obj.value = val
            else:
                db.add(SystemConfig(key="subtitle_download_config", value=val))
            await db.commit()
        _cfg_cache = config
        _cfg_cache_at = time.monotonic()
        return True
    except Exception as e:
        logger.error("[SubDL] 保存配置失败: %s", e)
        return False


class SubtitleDownloadService:
    """字幕自动下载服务"""

    async def search_subtitles(self, query: str, tmdb_id: int = 0,
                                languages: str = "zh-cn,zh-tw,en") -> list:
        cfg = await _load_config()
        api_key = cfg.get("api_key", "")
        if not api_key:
            return []

        params = {"query": query, "languages": languages}
        if tmdb_id:
            params["tmdb_id"] = tmdb_id

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{_OS_API}/subtitles", params=params,
                    headers={"Api-Key": api_key, "User-Agent": "MisakaMediaFlow v1.0"})
                if resp.status_code != 200:
                    logger.warning("[SubDL] 搜索失败 HTTP %d", resp.status_code)
                    return []
                data = resp.json()
                results = []
                for item in data.get("data", [])[:20]:
                    attrs = item.get("attributes", {})
                    files = attrs.get("files", [])
                    results.append({
                        "id": item.get("id"),
                        "language": attrs.get("language", ""),
                        "release": attrs.get("release", ""),
                        "download_count": attrs.get("download_count", 0),
                        "file_id": files[0].get("file_id") if files else None,
                        "file_name": files[0].get("file_name", "") if files else "",
                    })
                return results
        except Exception as e:
            logger.error("[SubDL] 搜索异常: %s", e)
            return []

    async def download_subtitle(self, file_id: int, save_path: str) -> bool:
        cfg = await _load_config()
        api_key = cfg.get("api_key", "")
        if not api_key or not file_id:
            return False

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Step 1: 获取下载链接
                resp = await client.post(f"{_OS_API}/download",
                    json={"file_id": file_id},
                    headers={"Api-Key": api_key, "User-Agent": "MisakaMediaFlow v1.0"})
                if resp.status_code != 200:
                    logger.warning("[SubDL] 下载链接获取失败: %d", resp.status_code)
                    return False
                dl_url = resp.json().get("link")
                if not dl_url:
                    return False

                # Step 2: 下载文件
                resp2 = await client.get(dl_url)
                if resp2.status_code != 200:
                    return False

                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                Path(save_path).write_bytes(resp2.content)
                logger.info("[SubDL] 字幕已下载: %s", save_path)
                return True
        except Exception as e:
            logger.error("[SubDL] 下载失败: %s", e)
            return False

    async def auto_download_for_strm(self, strm_path: str) -> Optional[str]:
        """为 STRM 文件自动搜索并下载字幕"""
        cfg = await _load_config()
        if not cfg.get("enabled") or not cfg.get("api_key"):
            return None

        strm_file = Path(strm_path)
        if not strm_file.exists():
            return None

        # 检查是否已有字幕
        for ext in [".srt", ".ass", ".ssa"]:
            if strm_file.with_suffix(ext).exists():
                return None  # 已有字幕

        # 用文件名搜索
        query = strm_file.stem
        langs = cfg.get("languages", "zh-cn,zh-tw,en")
        results = await self.search_subtitles(query, languages=langs)

        if not results:
            return None

        # 取第一个结果
        best = results[0]
        if not best.get("file_id"):
            return None

        # 确定保存路径
        sub_ext = Path(best["file_name"]).suffix if best.get("file_name") else ".srt"
        save_path = str(strm_file.with_suffix(sub_ext))

        ok = await self.download_subtitle(best["file_id"], save_path)
        return save_path if ok else None
