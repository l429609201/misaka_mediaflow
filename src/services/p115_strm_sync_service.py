# src/services/p115_strm_sync_service.py
# 115 STRM 全量/增量生成服务 + 生活事件监控

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

import httpx

from src.db import get_async_session_local
from src.db.models.system import SystemConfig
from sqlalchemy import select

logger = logging.getLogger(__name__)

# SystemConfig 存储 key
_STRM_SYNC_CONFIG_KEY = "p115_strm_sync_config"
_STRM_SYNC_STATUS_KEY = "p115_strm_sync_status"

# 视频文件扩展名（与 p115_settings 中的 file_extensions 一致）
_DEFAULT_VIDEO_EXTS = {"mp4", "mkv", "avi", "ts", "iso", "mov", "m2ts", "rmvb", "flv", "wmv", "m4v"}

# 115 生活事件接口
_LIFE_URL = "https://life.115.com/api/1.0/web/1.0/life_list"


def _get_manager():
    """延迟导入避免循环依赖"""
    from src.adapters.storage.p115 import P115Manager
    return P115Manager()


async def _load_config_from_db() -> dict:
    """从数据库读取 STRM 同步配置"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _STRM_SYNC_CONFIG_KEY)
        )
        cfg = result.scalars().first()
        if cfg and cfg.value:
            try:
                return json.loads(cfg.value)
            except Exception:
                pass
    return {}


async def _save_status_to_db(status: dict):
    """保存同步状态到数据库"""
    from src.core.timezone import tm
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _STRM_SYNC_STATUS_KEY)
        )
        cfg = result.scalars().first()
        value = json.dumps(status, ensure_ascii=False)
        if cfg:
            cfg.value = value
            cfg.updated_at = tm.now()
        else:
            cfg = SystemConfig(key=_STRM_SYNC_STATUS_KEY, value=value, description="115 STRM 同步状态")
            db.add(cfg)
        await db.commit()


async def _load_status_from_db() -> dict:
    """从数据库读取同步状态"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _STRM_SYNC_STATUS_KEY)
        )
        cfg = result.scalars().first()
        if cfg and cfg.value:
            try:
                return json.loads(cfg.value)
            except Exception:
                pass
    return {}


class P115StrmSyncService:
    """115 STRM 全量/增量生成服务"""

    def __init__(self):
        self._running = False          # 是否正在执行同步
        self._current_task: Optional[asyncio.Task] = None
        self._progress = {}            # 实时进度

    async def get_config(self) -> dict:
        """获取同步配置"""
        defaults = {
            "sync_pairs": [],          # [{cloud_path, strm_path}]
            "file_extensions": "mp4,mkv,avi,ts,iso,mov,m2ts",
            "strm_link_host": "",      # STRM 链接地址
            "clean_invalid": True,     # 是否清理失效 STRM
        }
        saved = await _load_config_from_db()
        return {**defaults, **saved}

    async def save_config(self, config: dict) -> bool:
        """保存同步配置"""
        from src.core.timezone import tm
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _STRM_SYNC_CONFIG_KEY)
            )
            cfg = result.scalars().first()
            value = json.dumps(config, ensure_ascii=False)
            if cfg:
                cfg.value = value
                cfg.updated_at = tm.now()
            else:
                cfg = SystemConfig(key=_STRM_SYNC_CONFIG_KEY, value=value, description="115 STRM 同步配置")
                db.add(cfg)
            await db.commit()
        return True

    async def get_status(self) -> dict:
        """获取同步状态"""
        status = await _load_status_from_db()
        status["running"] = self._running
        status["progress"] = self._progress
        return status

    def _get_video_exts(self, config: dict) -> set:
        """从配置中获取视频扩展名集合"""
        exts_str = config.get("file_extensions", "")
        if exts_str:
            return {e.strip().lower().lstrip(".") for e in exts_str.split(",") if e.strip()}
        return _DEFAULT_VIDEO_EXTS

    def _get_link_host(self, config: dict) -> str:
        """获取 STRM 链接地址"""
        host = config.get("strm_link_host", "").strip().rstrip("/")
        if not host:
            from src.core.config import settings
            host = (settings.server.external_url or "").rstrip("/")
        if not host:
            from src.core.config import settings
            host = f"http://127.0.0.1:{settings.server.go_port}"
        return host

    async def trigger_full_sync(self) -> dict:
        """触发全量 STRM 生成（后台异步执行）"""
        if self._running:
            return {"success": False, "message": "正在同步中，请稍后再试"}
        self._current_task = asyncio.create_task(self._do_full_sync())
        return {"success": True, "message": "全量同步已启动"}

    async def trigger_inc_sync(self) -> dict:
        """触发增量 STRM 生成（后台异步执行）"""
        if self._running:
            return {"success": False, "message": "正在同步中，请稍后再试"}
        self._current_task = asyncio.create_task(self._do_inc_sync())
        return {"success": True, "message": "增量同步已启动"}

    async def _do_full_sync(self):
        """执行全量同步"""
        self._running = True
        start_time = time.time()
        stats = {"created": 0, "skipped": 0, "removed": 0, "errors": 0}
        self._progress = {"stage": "scanning", **stats}

        try:
            config = await self.get_config()
            manager = _get_manager()
            if not manager.enabled or not manager.ready:
                logger.warning("[全量STRM] 115 未启用或未就绪")
                return

            video_exts = self._get_video_exts(config)
            link_host = self._get_link_host(config)
            sync_pairs = config.get("sync_pairs", [])

            if not sync_pairs:
                logger.warning("[全量STRM] 未配置同步路径对")
                return

            for pair in sync_pairs:
                cloud_path = pair.get("cloud_path", "").strip()
                strm_root = pair.get("strm_path", "").strip()
                if not cloud_path or not strm_root:
                    continue
                # 解析云盘路径对应的 cid
                start_cid = await self._resolve_cloud_cid(manager, cloud_path)
                if not start_cid:
                    logger.warning("[全量STRM] 路径无法解析，跳过: %s", cloud_path)
                    continue
                logger.info("[全量STRM] 开始扫描: %s (cid=%s) → %s", cloud_path, start_cid, strm_root)
                pair_stats = await self._sync_dir_recursive(
                    manager=manager,
                    cid=start_cid,
                    cloud_path=cloud_path,
                    strm_root=Path(strm_root),
                    rel_path=Path("."),
                    video_exts=video_exts,
                    link_host=link_host,
                    full=True,
                    last_sync_time=0,
                )
                for k in stats:
                    stats[k] += pair_stats.get(k, 0)
                self._progress = {"stage": "scanning", **stats}

        except Exception as e:
            logger.error("[全量STRM] 异常: %s", e, exc_info=True)
            stats["errors"] += 1
        finally:
            elapsed = round(time.time() - start_time, 1)
            status = {
                "last_full_sync": int(time.time()),
                "last_full_sync_stats": stats,
                "last_full_sync_elapsed": elapsed,
            }
            await _save_status_to_db(status)
            self._running = False
            self._progress = {"stage": "done", **stats}
            logger.info("[全量STRM] 完成: %s 耗时 %.1fs", stats, elapsed)

    async def _do_inc_sync(self):
        """执行增量同步（只处理 mtime > last_sync_time 的文件）"""
        self._running = True
        start_time = time.time()
        stats = {"created": 0, "skipped": 0, "removed": 0, "errors": 0}
        self._progress = {"stage": "scanning", **stats}

        try:
            config = await self.get_config()
            saved_status = await _load_status_from_db()
            # 取上次全量或增量同步时间中的较大值
            last_sync_time = max(
                saved_status.get("last_full_sync", 0),
                saved_status.get("last_inc_sync", 0),
            )

            manager = _get_manager()
            if not manager.enabled or not manager.ready:
                logger.warning("[增量STRM] 115 未启用或未就绪")
                return

            video_exts = self._get_video_exts(config)
            link_host = self._get_link_host(config)
            sync_pairs = config.get("sync_pairs", [])

            if not sync_pairs:
                logger.warning("[增量STRM] 未配置同步路径对")
                return

            for pair in sync_pairs:
                cloud_path = pair.get("cloud_path", "").strip()
                strm_root = pair.get("strm_path", "").strip()
                if not cloud_path or not strm_root:
                    continue
                start_cid = await self._resolve_cloud_cid(manager, cloud_path)
                if not start_cid:
                    logger.warning("[增量STRM] 路径无法解析，跳过: %s", cloud_path)
                    continue
                logger.info("[增量STRM] 开始扫描(last_sync=%d): %s (cid=%s) → %s", last_sync_time, cloud_path, start_cid, strm_root)
                pair_stats = await self._sync_dir_recursive(
                    manager=manager,
                    cid=start_cid,
                    cloud_path=cloud_path,
                    strm_root=Path(strm_root),
                    rel_path=Path("."),
                    video_exts=video_exts,
                    link_host=link_host,
                    full=False,
                    last_sync_time=last_sync_time,
                )
                for k in stats:
                    stats[k] += pair_stats.get(k, 0)
                self._progress = {"stage": "scanning", **stats}

        except Exception as e:
            logger.error("[增量STRM] 异常: %s", e, exc_info=True)
            stats["errors"] += 1
        finally:
            elapsed = round(time.time() - start_time, 1)
            status = {
                "last_inc_sync": int(time.time()),
                "last_inc_sync_stats": stats,
                "last_inc_sync_elapsed": elapsed,
            }
            await _save_status_to_db(status)
            self._running = False
            self._progress = {"stage": "done", **stats}
            logger.info("[增量STRM] 完成: %s 耗时 %.1fs", stats, elapsed)

    async def _resolve_cloud_cid(self, manager, cloud_path: str) -> str:
        """将云盘路径解析为 cid（目录 ID）。
        策略：从根目录 cid='0' 开始，按路径段逐层查找对应目录。
        若路径为 / 或空，直接返回 '0'（根目录）。
        """
        cloud_path = cloud_path.strip().strip("/")
        if not cloud_path:
            return "0"
        segments = [s for s in cloud_path.split("/") if s]
        cid = "0"
        current_path = ""
        for seg in segments:
            current_path = f"{current_path}/{seg}"
            try:
                entries = await manager.adapter.list_files(current_path, cid=cid)
                found = next((e for e in entries if e.is_dir and e.name == seg), None)
                if found:
                    cid = found.file_id
                else:
                    logger.warning("[STRM同步] 路径段未找到: %s (parent_cid=%s)", seg, cid)
                    return ""
            except Exception as e:
                logger.error("[STRM同步] 解析路径失败 %s: %s", current_path, e)
                return ""
        return cid

    async def _sync_dir_recursive(
        self, manager, cid: str, cloud_path: str,
        strm_root: Path, rel_path: Path,
        video_exts: set, link_host: str,
        full: bool, last_sync_time: int,
        depth: int = 0,
    ) -> dict:
        """递归同步目录（以 cid 为主键，cloud_path 仅用于日志）"""
        if depth > 30:
            return {"created": 0, "skipped": 0, "removed": 0, "errors": 0}

        stats = {"created": 0, "skipped": 0, "removed": 0, "errors": 0}
        try:
            entries = await manager.adapter.list_files(cloud_path, cid=cid)
        except Exception as e:
            logger.error("[STRM同步] 列目录失败 cid=%s path=%s: %s", cid, cloud_path, e)
            stats["errors"] += 1
            return stats

        sub_tasks = []
        for entry in entries:
            if entry.is_dir:
                sub_tasks.append(self._sync_dir_recursive(
                    manager=manager,
                    cid=entry.file_id,
                    cloud_path=entry.path,
                    strm_root=strm_root,
                    rel_path=rel_path / entry.name,
                    video_exts=video_exts,
                    link_host=link_host,
                    full=full,
                    last_sync_time=last_sync_time,
                    depth=depth + 1,
                ))
            else:
                ext = Path(entry.name).suffix.lstrip(".").lower()
                if ext not in video_exts:
                    continue
                mtime = int(entry.mtime) if entry.mtime else 0
                if not full and mtime <= last_sync_time:
                    stats["skipped"] += 1
                    continue
                if not entry.pick_code:
                    stats["errors"] += 1
                    continue
                # 生成 STRM 文件
                strm_dir = strm_root / rel_path
                strm_dir.mkdir(parents=True, exist_ok=True)
                strm_filename = Path(entry.name).with_suffix(".strm").name
                strm_file = strm_dir / strm_filename
                strm_content = f"{link_host}/p115/play/{entry.pick_code}/{entry.name}"
                try:
                    strm_file.write_text(strm_content, encoding="utf-8")
                    stats["created"] += 1
                    logger.debug("[STRM同步] 生成: %s", strm_file)
                except Exception as e:
                    logger.error("[STRM同步] 写文件失败 %s: %s", strm_file, e)
                    stats["errors"] += 1

        # 并发处理子目录（最多8并发）
        if sub_tasks:
            for i in range(0, len(sub_tasks), 8):
                results = await asyncio.gather(*sub_tasks[i:i+8], return_exceptions=True)
                for r in results:
                    if isinstance(r, dict):
                        for k in stats:
                            stats[k] += r.get(k, 0)

        return stats

