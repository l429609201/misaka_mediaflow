# src/services/p115_organize_service.py
# 115 文件整理执行器
# 分类逻辑由 src/services/classify_engine.py 统一管理。

import asyncio, json, logging, time
from typing import Optional
from sqlalchemy import select
from src.db import get_async_session_local
from src.db.models.system import SystemConfig
import src.services.classify_engine as classify_engine

logger = logging.getLogger(__name__)
_STATUS_KEY   = "p115_organize_status"
_115_MOVE_URL = "https://webapi.115.com/files/move"


def _get_manager():
    from src.adapters.storage.p115 import P115Manager
    return P115Manager()


class P115OrganizeService:
    def __init__(self):
        self._running   = False
        self._progress: dict = {}

    async def get_status(self) -> dict:
        async with get_async_session_local() as db:
            row = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _STATUS_KEY)
            )
            cfg = row.scalars().first()
            status: dict = {}
            if cfg and cfg.value:
                try:
                    status = json.loads(cfg.value)
                except Exception:
                    pass
        status["running"]  = self._running
        status["progress"] = self._progress
        return status

    async def trigger_organize(self, source_paths: list = None) -> dict:
        """触发整理。source_paths 由调用方传入；None 时从 path_mapping 读取。"""
        if self._running:
            return {"success": False, "message": "整理任务正在进行中"}
        asyncio.create_task(self._do_organize(source_paths=source_paths))
        return {"success": True, "message": "整理任务已启动"}

    async def _do_organize(self, source_paths: list = None):
        self._running  = True
        start_time     = time.time()
        stats          = {"moved": 0, "skipped": 0, "errors": 0, "unrecognized": 0}
        self._progress = {"stage": "scanning", **stats}
        try:
            cfg = await classify_engine.get_config()
            if not cfg.get("enabled", True):
                logger.info("[整理] 分类引擎已禁用，跳过")
                return
            target_root      = cfg.get("target_root", "").strip()
            unrecognized_dir = cfg.get("unrecognized_dir", "").strip()
            dry_run          = cfg.get("dry_run", False)
            categories       = cfg.get("categories", classify_engine.DEFAULT_CATEGORIES)
            manager = _get_manager()
            if not manager.enabled or not manager.ready:
                logger.warning("[整理] 115 未启用或未就绪")
                return
            if not source_paths:
                pm  = await self._load_path_mapping()
                src = pm.get("organize_source", "").strip()
                source_paths = [src] if src else []
            if not source_paths:
                logger.warning("[整理] 未配置待整理目录，退出")
                return
            target_root_id = ""
            if target_root:
                target_root_id = await self._ensure_dir(manager, target_root)
                if not target_root_id:
                    logger.error("[整理] 目标根目录无效: %s", target_root)
                    return
            unrecognized_cid = ""
            if unrecognized_dir:
                unrecognized_cid = await self._ensure_dir(manager, unrecognized_dir)
            cat_cid_map: dict = {}
            if target_root_id:
                for cat in categories:
                    name    = cat.get("name", "")
                    sub_dir = cat.get("target_dir", name)
                    if not name or not sub_dir:
                        continue
                    cid = await self._ensure_dir(
                        manager, f"{target_root}/{sub_dir}", parent_id=target_root_id,
                    )
                    if cid:
                        cat_cid_map[name] = cid
            tmdb_ok = await classify_engine.is_meta_available()
            logger.info("[整理] TMDB %s", "已配置" if tmdb_ok else "未配置，仅本地规则")
            for src_path in source_paths:
                await self._process_dir(
                    manager, src_path, categories, cat_cid_map,
                    unrecognized_cid, dry_run, tmdb_ok, stats,
                )
                self._progress = {"stage": "organizing", **stats}
        except Exception as e:
            logger.error("[整理] 异常: %s", e, exc_info=True)
            stats["errors"] += 1
        finally:
            await self._save_status(stats, time.time() - start_time)
            self._running  = False
            self._progress = {"stage": "done", **stats}

    async def _process_dir(
        self, manager, src_path, categories, cat_cid_map,
        unrecognized_cid, dry_run, tmdb_ok, stats,
    ):
        logger.info("[整理] 扫描: %s", src_path)
        try:
            entries = await manager.adapter.list_files(src_path, cid="0")
        except Exception as e:
            logger.error("[整理] 扫描目录失败 %s: %s", src_path, e)
            return
        dirname = src_path.rstrip("/").rsplit("/", 1)[-1]
        for entry in entries:
            if entry.is_dir:
                continue
            filename  = entry.name
            tmdb_info: dict = {}
            is_movie: Optional[bool] = None
            title, year = filename, None
            try:
                from src.utils.filename_parser import parse_filename
                parsed   = parse_filename(filename)
                title    = parsed.title or filename
                year     = parsed.year
                if parsed.season is not None or parsed.episode is not None:
                    is_movie = False
                elif parsed.is_movie:
                    is_movie = True
            except Exception:
                pass
            if tmdb_ok:
                if is_movie is None:
                    tmdb_info = await classify_engine.fetch_meta_info(title, True, year)
                    if not tmdb_info:
                        tmdb_info = await classify_engine.fetch_meta_info(title, False, year)
                else:
                    tmdb_info = await classify_engine.fetch_meta_info(title, is_movie, year)
            category = classify_engine.detect_category(filename, dirname, tmdb_info, categories, is_movie=is_movie)
            if not category or not cat_cid_map.get(category):
                if unrecognized_cid:
                    if dry_run:
                        logger.info("[整理][试运行] 未识别 %s -> 未识别目录", filename)
                    else:
                        ok = await self._move_file(manager, entry.file_id, unrecognized_cid)
                        stats["unrecognized" if ok else "errors"] += 1
                else:
                    stats["skipped"] += 1
                continue
            if dry_run:
                logger.info("[整理][试运行] %s -> %s", filename, category)
                stats["moved"] += 1
                continue
            ok = await self._move_file(manager, entry.file_id, cat_cid_map[category])
            if ok:
                stats["moved"] += 1
                logger.info("[整理] %s -> %s", filename, category)
            else:
                stats["errors"] += 1

    async def _load_path_mapping(self) -> dict:
        try:
            async with get_async_session_local() as db:
                row = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == "p115_path_mapping")
                )
                cfg = row.scalars().first()
                if cfg and cfg.value:
                    return json.loads(cfg.value)
        except Exception as e:
            logger.warning("[整理] 读取 path_mapping 失败: %s", e)
        return {}

    async def _ensure_dir(self, manager, path: str, parent_id: str = "") -> str:
        try:
            entries     = await manager.adapter.list_files(path, cid=parent_id or "0")
            target_name = path.rstrip("/").rsplit("/", 1)[-1]
            for e in entries:
                if e.is_dir and e.name == target_name:
                    return e.file_id
        except Exception:
            pass
        return ""

    async def _move_file(self, manager, file_id: str, target_cid: str) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    _115_MOVE_URL,
                    data={"fid[0]": file_id, "pid": target_cid},
                    headers=manager.adapter._auth.get_cookie_headers(),
                )
                return bool(resp.json().get("state"))
        except Exception as e:
            logger.error("[整理] 移动文件失败 fid=%s: %s", file_id, e)
            return False

    async def _save_status(self, stats: dict, elapsed: float):
        from src.core.timezone import tm
        val = {
            "last_organize":         int(time.time()),
            "last_organize_stats":   stats,
            "last_organize_elapsed": round(elapsed, 1),
        }
        async with get_async_session_local() as db:
            row   = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _STATUS_KEY)
            )
            cfg   = row.scalars().first()
            value = json.dumps(val, ensure_ascii=False)
            if cfg:
                cfg.value      = value
                cfg.updated_at = tm.now()
            else:
                db.add(SystemConfig(
                    key=_STATUS_KEY, value=value,
                    description="115 整理分类执行状态",
                ))
            await db.commit()
        logger.info("[整理] 完成: %s 耗时 %.1fs", stats, elapsed)
