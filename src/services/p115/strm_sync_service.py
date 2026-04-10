# src/services/p115/strm_sync_service.py
# 115 STRM 全量/增量生成服务 — 调度层
# 职责：任务调度、进度管理、配置读写、状态持久化。
# 遍历/写文件/DB操作均委托给 modules/ 子模块。

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from src.services.p115.modules import (
    load_strm_config, save_strm_config,
    load_strm_status, save_strm_status,
    load_p115_settings, get_url_template,
    get_video_exts, get_link_host, resolve_sync_pairs,
    iter_and_write_strm, resolve_cloud_cid,
    save_fscache_and_strmfile,
)
from src.services.p115.modules.db_ops import load_fscache_tree
from src.services.task_manager import get_task_manager

logger = logging.getLogger(__name__)


def _get_manager():
    from src.adapters.storage.p115 import P115Manager
    return P115Manager()


class P115StrmSyncService:
    """115 STRM 全量/增量生成服务（调度层）"""

    def __init__(self):
        self._running = False
        self._current_task: Optional[asyncio.Task] = None
        self._progress: dict = {}
        self._api_interval: float = 1.0

    # ── 配置 / 状态 ───────────────────────────────────────────────────────────

    async def get_config(self) -> dict:
        """获取同步配置（默认值 + 数据库持久化值合并）"""
        defaults = {
            "sync_pairs":          [],
            "file_extensions":     "mp4,mkv,avi,ts,iso,mov,m2ts",
            "strm_link_host":      "",
            "clean_invalid":       True,
            "full_sync_cfg":       {"use_custom": False, "cloud_path": "", "strm_path": ""},
            "inc_sync_cfg":        {"use_custom": False, "cloud_path": "", "strm_path": ""},
            "full_overwrite_mode": "skip",
            # 刮削配置
            "enable_scrape":         False,
            "scrape_download_image": True,
            "episode_group_id":      "",
            # Cron 定时全量同步（5段表达式，空=不启用）
            "full_sync_cron":        "",
        }
        saved = await load_strm_config()
        return {**defaults, **saved}

    async def save_config(self, config: dict) -> bool:
        """保存同步配置，并同步更新 APScheduler cron job"""
        await save_strm_config(config)
        # 保存后立即更新调度器
        self._apply_cron(config.get("full_sync_cron", ""))
        return True

    def _apply_cron(self, cron_expr: str) -> None:
        """注册或移除全量同步定时任务"""
        from src.core.scheduler import add_cron_job, scheduler
        JOB_ID = "p115_full_sync_cron"
        if not cron_expr or not cron_expr.strip():
            if scheduler.get_job(JOB_ID):
                scheduler.remove_job(JOB_ID)
                logger.info("[STRM Cron] 已移除定时全量同步")
            return
        import asyncio as _aio

        async def _cron_full_sync():
            logger.info("[STRM Cron] 定时触发全量同步")
            await self.trigger_full_sync()

        def _run():
            loop = _aio.get_event_loop()
            loop.create_task(_cron_full_sync())

        add_cron_job(_run, cron_expr.strip(), JOB_ID)
        logger.info("[STRM Cron] 已注册定时全量同步: %s", cron_expr)

    async def get_status(self) -> dict:
        """获取同步状态"""
        status = await load_strm_status()
        status["running"]  = self._running
        status["progress"] = self._progress
        return status

    # ── 本地 STRM 扫描与管理 ──────────────────────────────────────────────────

    async def scan_local_strm(self, strm_root: str = None) -> dict:
        """
        扫描本地 STRM 文件，统计数量和状态。

        Args:
            strm_root: 指定扫描目录，为空则扫描所有配置的 sync_pairs

        Returns:
            {
                "total": 总文件数,
                "valid": 有效文件数,
                "invalid": 无效文件数（对应网盘文件已删除）,
                "missing_nfo": 缺失 NFO 的文件数,
                "paths": [扫描的路径列表]
            }
        """
        from src.services.p115.modules import resolve_sync_pairs

        config = await self.get_config()

        # 确定扫描路径
        if strm_root:
            scan_paths = [Path(strm_root)]
        else:
            sync_pairs = await resolve_sync_pairs(config)
            scan_paths = [Path(pair["strm_path"]) for pair in sync_pairs if pair.get("strm_path")]

        if not scan_paths:
            return {"error": "未配置 STRM 路径"}

        stats = {
            "total": 0,
            "valid": 0,
            "invalid": 0,
            "missing_nfo": 0,
            "paths": [str(p) for p in scan_paths]
        }

        for strm_path in scan_paths:
            if not strm_path.exists():
                logger.warning("[STRM扫描] 路径不存在: %s", strm_path)
                continue

            for strm_file in strm_path.rglob("*.strm"):
                stats["total"] += 1

                # 检查 NFO 是否存在
                nfo_file = strm_file.with_suffix(".nfo")
                if not nfo_file.exists():
                    stats["missing_nfo"] += 1

                # 读取 STRM 内容，检查是否有效
                try:
                    content = strm_file.read_text(encoding="utf-8").strip()
                    if content and ("pickcode=" in content or "http" in content):
                        stats["valid"] += 1
                    else:
                        stats["invalid"] += 1
                except Exception as e:
                    logger.warning("[STRM扫描] 读取失败 %s: %s", strm_file, e)
                    stats["invalid"] += 1

        logger.info("[STRM扫描] 完成: %s", stats)
        return stats

    async def clean_invalid_strm(self, strm_root: str = None, dry_run: bool = True) -> dict:
        """
        清理无效的 STRM 文件及其关联的 NFO/图片。

        Args:
            strm_root: 指定清理目录，为空则清理所有配置的 sync_pairs
            dry_run: 试运行模式，只统计不实际删除

        Returns:
            {
                "deleted_strm": 删除的 STRM 文件数,
                "deleted_nfo": 删除的 NFO 文件数,
                "deleted_images": 删除的图片文件数,
                "dry_run": 是否为试运行
            }
        """
        from src.services.p115.modules import resolve_sync_pairs

        config = await self.get_config()

        # 确定清理路径
        if strm_root:
            scan_paths = [Path(strm_root)]
        else:
            sync_pairs = await resolve_sync_pairs(config)
            scan_paths = [Path(pair["strm_path"]) for pair in sync_pairs if pair.get("strm_path")]

        if not scan_paths:
            return {"error": "未配置 STRM 路径"}

        stats = {
            "deleted_strm": 0,
            "deleted_nfo": 0,
            "deleted_images": 0,
            "dry_run": dry_run
        }

        for strm_path in scan_paths:
            if not strm_path.exists():
                continue

            for strm_file in strm_path.rglob("*.strm"):
                # 检查 STRM 是否有效
                try:
                    content = strm_file.read_text(encoding="utf-8").strip()
                    is_valid = content and ("pickcode=" in content or "http" in content)
                except Exception:
                    is_valid = False

                if not is_valid:
                    # 删除 STRM 文件
                    if not dry_run:
                        strm_file.unlink(missing_ok=True)
                    stats["deleted_strm"] += 1

                    # 删除关联的 NFO
                    nfo_file = strm_file.with_suffix(".nfo")
                    if nfo_file.exists():
                        if not dry_run:
                            nfo_file.unlink(missing_ok=True)
                        stats["deleted_nfo"] += 1

                    # 删除关联的图片（poster.jpg, fanart.jpg 等）
                    for img_name in ["poster.jpg", "fanart.jpg", "backdrop.jpg"]:
                        img_file = strm_file.parent / img_name
                        if img_file.exists():
                            if not dry_run:
                                img_file.unlink(missing_ok=True)
                            stats["deleted_images"] += 1

        logger.info("[STRM清理] 完成: %s", stats)
        return stats

    async def rescrape_missing_nfo(self, strm_root: str = None) -> dict:
        """
        补刮削：扫描缺失 NFO 的 STRM 文件并重新刮削。

        Args:
            strm_root: 指定目录，为空则处理所有配置的 sync_pairs

        Returns:
            {
                "total": 扫描的 STRM 总数,
                "missing_nfo": 缺失 NFO 的数量,
                "scraped": 成功刮削的数量,
                "failed": 刮削失败的数量
            }
        """
        from src.services.p115.modules import resolve_sync_pairs
        from src.services.metadata_service import metadata_service
        from src.services.p115.modules.scraper import Scraper
        from src.db.database import get_async_session_local
        from src.db.models import SystemConfig
        from sqlalchemy import select
        import json as _json

        config = await self.get_config()

        # 确定扫描路径
        if strm_root:
            scan_paths = [Path(strm_root)]
        else:
            sync_pairs = await resolve_sync_pairs(config)
            scan_paths = [Path(pair["strm_path"]) for pair in sync_pairs if pair.get("strm_path")]

        if not scan_paths:
            return {"error": "未配置 STRM 路径"}

        # 获取 TMDB provider
        tmdb = await metadata_service.get_provider("tmdb")
        if not tmdb:
            return {"error": "TMDB 未配置"}

        # 读取刮削配置
        scrape_config = {}
        try:
            async with get_async_session_local() as db:
                result = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == "p115_scrape_config")
                )
                cfg = result.scalars().first()
                if cfg and cfg.value:
                    scrape_config = _json.loads(cfg.value)
        except Exception as e:
            logger.warning("[补刮削] 读取刮削配置失败: %s", e)

        movie_format = scrape_config.get("movie_format", "{title} ({year})/{title} ({year})")
        tv_format = scrape_config.get("tv_format", "{title} ({year})/Season {season:02d}/{title} - {season_episode} - {episode_title}")
        episode_group_id = config.get("episode_group_id", "")
        download_images = config.get("scrape_download_image", True)

        scraper = Scraper(
            tmdb,
            episode_group_id=episode_group_id,
            download_images=download_images,
            movie_format=movie_format,
            tv_format=tv_format
        )

        stats = {
            "total": 0,
            "missing_nfo": 0,
            "scraped": 0,
            "failed": 0
        }

        for strm_path in scan_paths:
            if not strm_path.exists():
                continue

            for strm_file in strm_path.rglob("*.strm"):
                stats["total"] += 1
                nfo_file = strm_file.with_suffix(".nfo")

                if not nfo_file.exists():
                    stats["missing_nfo"] += 1
                    try:
                        success = await scraper.scrape_file(strm_file)
                        if success:
                            stats["scraped"] += 1
                        else:
                            stats["failed"] += 1
                    except Exception as e:
                        logger.error("[补刮削] 刮削失败 %s: %s", strm_file, e)
                        stats["failed"] += 1

        logger.info("[补刮削] 完成: %s", stats)
        return stats

    # ── 触发接口 ──────────────────────────────────────────────────────────────

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

    # ── 全量同步 ──────────────────────────────────────────────────────────────

    async def _do_full_sync(self):
        self._running = True
        start_time = time.time()
        stats = {"created": 0, "skipped": 0, "errors": 0}
        self._progress = {"stage": "scanning", **stats}
        tm = get_task_manager()
        task_id = await tm.create_task(
            task_name="全量 STRM 同步",
            task_category="p115_strm",
            task_type="full_sync",
            triggered_by="manual",
        )
        # 注册当前 asyncio.Task 引用，供终止功能使用
        if self._current_task:
            tm.register_task(task_id, self._current_task)

        try:
            config         = await self.get_config()
            manager        = _get_manager()
            if not manager.enabled or not manager.ready:
                logger.warning("【全量STRM生成】115 未启用或未就绪")
                await tm.complete_task(task_id, stats, error_message="115 未启用或未就绪")
                return

            video_exts     = get_video_exts(config)
            url_tmpl       = await get_url_template()
            sync_pairs     = resolve_sync_pairs(config, "full")
            p115_settings  = await load_p115_settings()
            # strm_link_host 保存在 p115_settings 中，需要从 p115_settings 读取
            link_host      = get_link_host(p115_settings)
            api_interval   = float(p115_settings.get("api_interval", 1.0))
            api_concurrent = int(p115_settings.get("api_concurrent", 3))
            # 目录树缓存 TTL：0 = 禁用，默认 24 小时
            fscache_ttl    = float(p115_settings.get("fscache_ttl_hours", 24.0))
            overwrite_mode = config.get("full_overwrite_mode", "skip")
            self._api_interval = api_interval

            logger.info("【全量STRM生成】配置: interval=%.1fs concurrent=%d overwrite=%s pairs=%d fscache_ttl=%.0fh",
                        api_interval, api_concurrent, overwrite_mode, len(sync_pairs), fscache_ttl)

            if not sync_pairs:
                logger.warning("【全量STRM生成】未配置同步路径对")
                await tm.complete_task(task_id, stats, error_message="未配置同步路径对")
                return

            for pair in sync_pairs:
                cloud_path = pair.get("cloud_path", "").strip()
                strm_root  = pair.get("strm_path", "").strip()
                if not cloud_path or not strm_root:
                    continue

                start_cid = await resolve_cloud_cid(manager, cloud_path)
                if not start_cid:
                    logger.warning("【全量STRM生成】获取 cid 失败，跳过: %s", cloud_path)
                    continue

                logger.info("【全量STRM生成】%s (cid=%s) → %s overwrite=%s",
                            cloud_path, start_cid, strm_root, overwrite_mode)

                # skip 模式下预加载 FsCache 缓存树，减少 API 调用
                fc_tree = None
                if overwrite_mode == "skip":
                    cloud_path_full = "/" + cloud_path.strip("/")
                    fc_tree = await load_fscache_tree(cloud_path_full, max_age_hours=fscache_ttl)

                pair_stats, fc_batch, sf_batch = await asyncio.to_thread(
                    iter_and_write_strm,
                    manager, start_cid, cloud_path,
                    Path(strm_root), video_exts, link_host, url_tmpl,
                    from_time=0,
                    overwrite_mode=overwrite_mode,
                    api_interval=api_interval,
                    fscache_tree=fc_tree,
                )
                for k in stats:
                    stats[k] += pair_stats.get(k, 0)
                self._progress = {"stage": "scanning", **stats}
                tm.update_progress(task_id, "running", stats)

                db_result = await save_fscache_and_strmfile(fc_batch, sf_batch)
                logger.info("【全量STRM生成】DB写入: FsCache=%d StrmFile=%d",
                            db_result["fscache"], db_result["strmfile"])

        except Exception as e:
            logger.error("【全量STRM生成】失败: %s", e, exc_info=True)
            stats["errors"] += 1
            await tm.complete_task(task_id, stats, error_message=str(e))
            # 通知：任务失败
            try:
                from src.services.notify_service import send as _notify
                await _notify("全量STRM同步失败", f"错误：{e}\n生成：{stats.get('created',0)} 个")
            except Exception:
                pass
        else:
            await tm.complete_task(task_id, stats)
            # 同步成功且启用了刮削 → 逐路径对批量刮削
            if config.get("enable_scrape"):
                await _run_scrape(config, sync_pairs)
            # 通知：任务成功
            try:
                from src.services.notify_service import send as _notify
                await _notify(
                    "全量STRM同步完成",
                    f"生成：{stats.get('created',0)} 个  跳过：{stats.get('skipped',0)} 个  失败：{stats.get('errors',0)} 个",
                )
            except Exception:
                pass
        finally:
            elapsed = round(time.time() - start_time, 1)
            await save_strm_status({
                "last_full_sync":         int(time.time()),
                "last_full_sync_stats":   stats,
                "last_full_sync_elapsed": elapsed,
            })
            self._running  = False
            self._progress = {"stage": "done", **stats}
            logger.info("【全量STRM生成】完成: 生成%d个 耗时%.1fs stats=%s",
                        stats.get("created", 0), elapsed, stats)

    # ── 增量同步 ──────────────────────────────────────────────────────────────

    async def _do_inc_sync(self):
        self._running = True
        start_time = time.time()
        stats = {"created": 0, "skipped": 0, "errors": 0}
        self._progress = {"stage": "scanning", **stats}
        tm = get_task_manager()
        task_id = await tm.create_task(
            task_name="增量 STRM 同步",
            task_category="p115_strm",
            task_type="inc_sync",
            triggered_by="manual",
        )
        # 注册当前 asyncio.Task 引用，供终止功能使用
        if self._current_task:
            tm.register_task(task_id, self._current_task)

        try:
            config         = await self.get_config()
            saved_status   = await load_strm_status()
            last_sync_time = max(
                saved_status.get("last_full_sync", 0),
                saved_status.get("last_inc_sync",  0),
            )
            manager        = _get_manager()
            if not manager.enabled or not manager.ready:
                logger.warning("【增量STRM生成】115 未启用或未就绪")
                await tm.complete_task(task_id, stats, error_message="115 未启用或未就绪")
                return

            video_exts    = get_video_exts(config)
            url_tmpl      = await get_url_template()
            sync_pairs    = resolve_sync_pairs(config, "inc")
            p115_settings = await load_p115_settings()
            # strm_link_host 保存在 p115_settings 中，需要从 p115_settings 读取
            link_host     = get_link_host(p115_settings)
            api_interval  = float(p115_settings.get("api_interval", 1.0))
            self._api_interval = api_interval

            if not sync_pairs:
                logger.warning("【增量STRM生成】未配置同步路径对")
                await tm.complete_task(task_id, stats, error_message="未配置同步路径对")
                return

            logger.info("【增量STRM生成】last_sync=%d pairs=%d", last_sync_time, len(sync_pairs))

            for pair in sync_pairs:
                cloud_path = pair.get("cloud_path", "").strip()
                strm_root  = pair.get("strm_path", "").strip()
                if not cloud_path or not strm_root:
                    continue

                start_cid = await resolve_cloud_cid(manager, cloud_path)
                if not start_cid:
                    logger.warning("【增量STRM生成】获取 cid 失败，跳过: %s", cloud_path)
                    continue

                logger.info("【增量STRM生成】%s (cid=%s) → %s last_sync=%d",
                            cloud_path, start_cid, strm_root, last_sync_time)

                pair_stats, fc_batch, sf_batch = await asyncio.to_thread(
                    iter_and_write_strm,
                    manager, start_cid, cloud_path,
                    Path(strm_root), video_exts, link_host, url_tmpl,
                    from_time=last_sync_time,
                    overwrite_mode="skip",
                    api_interval=api_interval,
                )
                for k in stats:
                    stats[k] += pair_stats.get(k, 0)
                self._progress = {"stage": "scanning", **stats}
                tm.update_progress(task_id, "running", stats)

                db_result = await save_fscache_and_strmfile(fc_batch, sf_batch)
                logger.info("【增量STRM生成】DB写入: FsCache=%d StrmFile=%d",
                            db_result["fscache"], db_result["strmfile"])

        except Exception as e:
            logger.error("【增量STRM生成】失败: %s", e, exc_info=True)
            stats["errors"] += 1
            await tm.complete_task(task_id, stats, error_message=str(e))
        else:
            await tm.complete_task(task_id, stats)
            # 同步成功且启用了刮削 → 逐路径对批量刮削
            if config.get("enable_scrape"):
                await _run_scrape(config, sync_pairs)
        finally:
            elapsed = round(time.time() - start_time, 1)
            await save_strm_status({
                "last_inc_sync":         int(time.time()),
                "last_inc_sync_stats":   stats,
                "last_inc_sync_elapsed": elapsed,
            })
            self._running  = False
            self._progress = {"stage": "done", **stats}
            logger.info("【增量STRM生成】完成: 生成%d个 耗时%.1fs stats=%s",
                        stats.get("created", 0), elapsed, stats)


async def _run_scrape(config: dict, sync_pairs: list) -> None:
    """
    同步完成后触发刮削。
    每个 sync_pair 的 strm_path 作为刮削根目录，
    由 Scraper.scrape_dir() 递归处理所有 .strm 文件。

    注意：刮削配置（重命名模板）复用"整理分类刮削"中的配置，
    从 p115_scrape_config 读取 movie_format 和 tv_format。
    """
    from src.services.metadata_service import metadata_service
    from src.services.p115.modules.scraper import Scraper
    from src.db.database import get_async_session_local
    from src.db.models import SystemConfig
    from sqlalchemy import select
    import json as _json

    tmdb = await metadata_service.get_provider("tmdb")
    if not tmdb:
        logger.warning("[Scraper] TMDB 未配置，跳过刮削")
        return

    # 从"整理分类刮削"配置中读取重命名模板
    scrape_config = {}
    try:
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == "p115_scrape_config")
            )
            cfg = result.scalars().first()
            if cfg and cfg.value:
                scrape_config = _json.loads(cfg.value)
    except Exception as e:
        logger.warning("[Scraper] 读取刮削配置失败: %s", e)

    # 使用整理分类刮削的模板配置
    movie_format = scrape_config.get("movie_format", "{title} ({year})/{title} ({year})")
    tv_format = scrape_config.get("tv_format", "{title} ({year})/Season {season:02d}/{title} - {season_episode} - {episode_title}")

    episode_group_id   = config.get("episode_group_id", "")
    download_images    = config.get("scrape_download_image", True)

    scraper = Scraper(
        tmdb,
        episode_group_id=episode_group_id,
        download_images=download_images,
        movie_format=movie_format,
        tv_format=tv_format
    )

    for pair in sync_pairs:
        strm_root = pair.get("strm_path", "").strip()
        if not strm_root:
            continue
        logger.info("[Scraper] 开始刮削: %s (使用整理分类刮削模板)", strm_root)
        try:
            result = await scraper.scrape_dir(Path(strm_root))
            logger.info("[Scraper] 刮削完成: %s → %s", strm_root, result)
        except Exception as e:
            logger.error("[Scraper] 刮削异常 %s: %s", strm_root, e, exc_info=True)
