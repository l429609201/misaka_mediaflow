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
            "enable_scrape":         False,   # 同步完成后自动刮削
            "scrape_download_image": True,    # 是否下载 poster/backdrop 图片
            "episode_group_id":      "",      # TMDB 剧集组 ID（留空=不用剧集组）
        }
        saved = await load_strm_config()
        return {**defaults, **saved}

    async def save_config(self, config: dict) -> bool:
        """保存同步配置"""
        await save_strm_config(config)
        return True

    async def get_status(self) -> dict:
        """获取同步状态"""
        status = await load_strm_status()
        status["running"]  = self._running
        status["progress"] = self._progress
        return status

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
        else:
            await tm.complete_task(task_id, stats)
            # 同步成功且启用了刮削 → 逐路径对批量刮削
            if config.get("enable_scrape"):
                await _run_scrape(config, sync_pairs)
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
    """
    from src.services.metadata_service import metadata_service
    from src.services.p115.modules.scraper import Scraper

    tmdb = await metadata_service.get_provider("tmdb")
    if not tmdb:
        logger.warning("[Scraper] TMDB 未配置，跳过刮削")
        return

    episode_group_id   = config.get("episode_group_id", "")
    download_images    = config.get("scrape_download_image", True)
    scraper = Scraper(tmdb, episode_group_id=episode_group_id, download_images=download_images)

    for pair in sync_pairs:
        strm_root = pair.get("strm_path", "").strip()
        if not strm_root:
            continue
        logger.info("[Scraper] 开始刮削: %s", strm_root)
        try:
            result = await scraper.scrape_dir(Path(strm_root))
            logger.info("[Scraper] 刮削完成: %s → %s", strm_root, result)
        except Exception as e:
            logger.error("[Scraper] 刮削异常 %s: %s", strm_root, e, exc_info=True)
