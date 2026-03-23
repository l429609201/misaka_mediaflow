# src/services/p115_strm_sync_service.py
# 115 STRM 全量/增量生成服务
#
# 增量同步参考 emby-toolkit / p115strmhelper 的实现策略：
#   - 全量：用 p115client.tool.iterdir.iter_files_with_path_skim 递归遍历整棵树
#   - 增量：优先用 p115client.tool 按 from_time 筛选新文件，
#           回退方案：webapi 列目录按时间倒序，遇到旧文件即停止（避免全量扫描）

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from src.db import get_async_session_local
from src.db.models.system import SystemConfig
from sqlalchemy import select

logger = logging.getLogger(__name__)

# SystemConfig 存储 key
_STRM_SYNC_CONFIG_KEY = "p115_strm_sync_config"
_STRM_SYNC_STATUS_KEY = "p115_strm_sync_status"

# 视频文件扩展名
_DEFAULT_VIDEO_EXTS = {"mp4", "mkv", "avi", "ts", "iso", "mov", "m2ts", "rmvb", "flv", "wmv", "m4v"}


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
            # 全量 / 增量 各自的自定义路径配置
            "full_sync_cfg": {"use_custom": False, "cloud_path": "", "strm_path": ""},
            "inc_sync_cfg":  {"use_custom": False, "cloud_path": "", "strm_path": ""},
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

    def _resolve_sync_pairs(self, config: dict, scope: str) -> list:
        """
        解析实际使用的路径对。
        scope: 'full' | 'inc'
        优先级：自定义路径(use_custom=True) > 全局 sync_pairs
        """
        cfg_key = f"{scope}_sync_cfg"
        custom = config.get(cfg_key, {})
        if custom.get("use_custom") and custom.get("cloud_path") and custom.get("strm_path"):
            return [{"cloud_path": custom["cloud_path"].strip(),
                     "strm_path":  custom["strm_path"].strip()}]
        # 回退到全局 sync_pairs
        return config.get("sync_pairs", [])

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

    # =========================================================================
    # 全量同步
    # =========================================================================

    async def _do_full_sync(self):
        """全量同步：用 iter_files_with_path_skim 遍历整棵树，无分页限制"""
        self._running = True
        start_time = time.time()
        stats = {"created": 0, "skipped": 0, "errors": 0}
        self._progress = {"stage": "scanning", **stats}

        try:
            config = await self.get_config()
            manager = _get_manager()
            if not manager.enabled or not manager.ready:
                logger.warning("[全量STRM] 115 未启用或未就绪")
                return

            video_exts = self._get_video_exts(config)
            link_host  = self._get_link_host(config)
            sync_pairs = self._resolve_sync_pairs(config, "full")

            if not sync_pairs:
                logger.warning("[全量STRM] 未配置同步路径对（请在STRM生成卡片中保存路径配置）")
                return

            for pair in sync_pairs:
                cloud_path = pair.get("cloud_path", "").strip()
                strm_root  = pair.get("strm_path", "").strip()
                if not cloud_path or not strm_root:
                    continue
                start_cid = await self._resolve_cloud_cid(manager, cloud_path)
                if not start_cid:
                    logger.warning("[全量STRM] 路径无法解析，跳过: %s", cloud_path)
                    continue
                logger.info("[全量STRM] 开始扫描: %s (cid=%s) → %s", cloud_path, start_cid, strm_root)
                pair_stats = await asyncio.to_thread(
                    self._iter_and_write_strm,
                    manager, start_cid, cloud_path,
                    Path(strm_root), video_exts, link_host,
                    from_time=0,
                )
                for k in stats:
                    stats[k] += pair_stats.get(k, 0)
                self._progress = {"stage": "scanning", **stats}

        except Exception as e:
            logger.error("[全量STRM] 异常: %s", e, exc_info=True)
            stats["errors"] += 1
        finally:
            elapsed = round(time.time() - start_time, 1)
            await _save_status_to_db({
                "last_full_sync": int(time.time()),
                "last_full_sync_stats": stats,
                "last_full_sync_elapsed": elapsed,
            })
            self._running = False
            self._progress = {"stage": "done", **stats}
            logger.info("[全量STRM] 完成: %s 耗时 %.1fs", stats, elapsed)

    # =========================================================================
    # 增量同步
    # =========================================================================

    async def _do_inc_sync(self):
        """增量同步：只处理上次同步时间之后新增的文件"""
        self._running = True
        start_time = time.time()
        stats = {"created": 0, "skipped": 0, "errors": 0}
        self._progress = {"stage": "scanning", **stats}

        try:
            config = await self.get_config()
            saved_status = await _load_status_from_db()
            last_sync_time = max(
                saved_status.get("last_full_sync", 0),
                saved_status.get("last_inc_sync", 0),
            )

            manager = _get_manager()
            if not manager.enabled or not manager.ready:
                logger.warning("[增量STRM] 115 未启用或未就绪")
                return

            video_exts = self._get_video_exts(config)
            link_host  = self._get_link_host(config)
            sync_pairs = self._resolve_sync_pairs(config, "inc")

            if not sync_pairs:
                logger.warning("[增量STRM] 未配置同步路径对（请在STRM生成卡片中保存路径配置）")
                return

            for pair in sync_pairs:
                cloud_path = pair.get("cloud_path", "").strip()
                strm_root  = pair.get("strm_path", "").strip()
                if not cloud_path or not strm_root:
                    continue
                start_cid = await self._resolve_cloud_cid(manager, cloud_path)
                if not start_cid:
                    logger.warning("[增量STRM] 路径无法解析，跳过: %s", cloud_path)
                    continue
                logger.info(
                    "[增量STRM] 开始扫描(last_sync=%d): %s (cid=%s) → %s",
                    last_sync_time, cloud_path, start_cid, strm_root,
                )
                pair_stats = await asyncio.to_thread(
                    self._iter_and_write_strm,
                    manager, start_cid, cloud_path,
                    Path(strm_root), video_exts, link_host,
                    from_time=last_sync_time,
                )
                for k in stats:
                    stats[k] += pair_stats.get(k, 0)
                self._progress = {"stage": "scanning", **stats}

        except Exception as e:
            logger.error("[增量STRM] 异常: %s", e, exc_info=True)
            stats["errors"] += 1
        finally:
            elapsed = round(time.time() - start_time, 1)
            await _save_status_to_db({
                "last_inc_sync": int(time.time()),
                "last_inc_sync_stats": stats,
                "last_inc_sync_elapsed": elapsed,
            })
            self._running = False
            self._progress = {"stage": "done", **stats}
            logger.info("[增量STRM] 完成: %s 耗时 %.1fs", stats, elapsed)

    # =========================================================================
    # 核心遍历 + 写 STRM（同步函数，在线程池中执行）
    # =========================================================================

    def _iter_and_write_strm(
        self,
        manager,
        cid: str,
        cloud_path: str,
        strm_root: Path,
        video_exts: set,
        link_host: str,
        from_time: int = 0,
    ) -> dict:
        """
        遍历 115 目录树，对每个视频文件写 .strm。
        优先使用 p115client.tool.iterdir.iter_files_with_path_skim（支持 from_time 过滤）。
        回退方案：p115client.tool.fs_files.iter_fs_files（逐页列目录，配合 mtime 过滤）。

        参考 emby-toolkit 的 generate_strm_files 和 p115strmhelper 的 full_pull 实现。
        """
        stats = {"created": 0, "skipped": 0, "errors": 0}
        p115_client = manager.adapter._get_p115_client()

        # ── 方案A：iterdir_traverse（p115client 标准 API，支持 web CK）──────
        # 注意：iter_files_with_path 内部有 fetch_dirs 子流程，
        #       会调用 download_folders_app（/os_windows/ufile/downfolders），
        #       该接口需要 windows cookie，与 web CK 不兼容，故改用 iterdir_traverse。
        # iterdir_traverse 仅使用 /web/2.0/files 接口，完全兼容 web CK。
        # 参考 p115strmhelper helper/strm/full.py 遍历策略。
        if p115_client is not None:
            try:
                from p115client.tool.iterdir import iterdir_traverse
                logger.debug("[STRM遍历] 使用 iterdir_traverse cid=%s from_time=%d", cid, from_time)
                scan_count = 0
                for item in iterdir_traverse(
                    client=p115_client,
                    cid=int(cid),
                    predicate=True,   # True = 只返回文件，跳过目录
                    cooldown=2,
                    app="web",        # 使用 web 接口，与 web CK 匹配
                ):
                    scan_count += 1
                    # normalize_attr 已标准化所有字段
                    name      = item.get("name", "")
                    pick_code = item.get("pickcode") or item.get("pick_code", "")
                    item_mtime = int(item.get("mtime") or item.get("ctime") or 0)
                    item_path  = item.get("path", "")

                    if from_time > 0 and item_mtime <= from_time:
                        logger.debug("[STRM遍历] 跳过旧文件(mtime=%d <= from_time=%d): %s",
                                     item_mtime, from_time, name)
                        stats["skipped"] += 1
                        continue
                    ext = Path(name).suffix.lstrip(".").lower()
                    if ext not in video_exts:
                        logger.debug("[STRM遍历] 跳过非视频文件: %s", name)
                        stats["skipped"] += 1
                        continue
                    if not pick_code:
                        logger.warning("[STRM遍历] 文件缺少 pickcode，跳过: %s", name)
                        stats["errors"] += 1
                        continue
                    # 参考 p115strmhelper: pickcode 必须是 17 位纯字母数字
                    if not (len(pick_code) == 17 and pick_code.isalnum()):
                        logger.warning("[STRM遍历] pickcode 格式无效(%r)，跳过: %s", pick_code, name)
                        stats["errors"] += 1
                        continue
                    rel = self._calc_rel_path(item_path, cloud_path)
                    result = self._write_strm(strm_root, rel, name, pick_code, link_host)
                    if result == "created":
                        stats["created"] += 1
                    elif result == "skipped":
                        stats["skipped"] += 1
                    else:
                        stats["errors"] += 1
                logger.debug("[STRM遍历] iterdir_traverse 共扫描 %d 项, stats=%s", scan_count, stats)
                return stats
            except ImportError:
                logger.debug("[STRM遍历] iterdir_traverse 不可用，使用回退方案")
            except Exception as e:
                logger.warning("[STRM遍历] iterdir_traverse 出错，使用回退方案: %s", e, exc_info=True)

        # ── 方案B：iter_fs_files 回退────────────────────────────────────────
        # iter_fs_files 每次 yield 一整页的 resp 字典，结构：
        #   resp["data"] = 原始文件/目录列表（未经 normalize_attr）
        #   原始字段：n=文件名, pc=pickcode, te=mtime, fid=文件ID（有fid表示是文件）
        if p115_client is not None:
            try:
                from p115client.tool.fs_files import iter_fs_files
                logger.debug("[STRM遍历] 使用 iter_fs_files cid=%s from_time=%d", cid, from_time)
                scan_count = 0
                for resp in iter_fs_files(p115_client, int(cid), cooldown=1.5, app="web",
                                          max_workers=0):  # max_workers=0 = 单线程串行，避免并发接口
                    for raw in resp.get("data", []):
                        scan_count += 1
                        # 原始字段：有 fid 的是文件，没有 fid 的是目录
                        if "fid" not in raw:
                            continue
                        # 原始字段：n=文件名, pc=pickcode, te=mtime
                        name       = raw.get("n") or raw.get("fn") or raw.get("name", "")
                        pick_code  = raw.get("pc") or raw.get("pickcode", "")
                        item_mtime = int(raw.get("te") or raw.get("t") or raw.get("mtime") or 0)

                        if from_time > 0 and item_mtime <= from_time:
                            logger.debug("[STRM遍历B] 跳过旧文件(mtime=%d <= from_time=%d): %s",
                                         item_mtime, from_time, name)
                            stats["skipped"] += 1
                            continue
                        ext = Path(name).suffix.lstrip(".").lower()
                        if ext not in video_exts:
                            logger.debug("[STRM遍历B] 跳过非视频文件: %s", name)
                            stats["skipped"] += 1
                            continue
                        if not pick_code:
                            logger.warning("[STRM遍历B] 文件缺少 pickcode，跳过: %s", name)
                            stats["errors"] += 1
                            continue
                        if not (len(pick_code) == 17 and pick_code.isalnum()):
                            logger.warning("[STRM遍历B] pickcode 格式无效(%r)，跳过: %s", pick_code, name)
                            stats["errors"] += 1
                            continue
                        # iter_fs_files 不包含完整路径，路径留空走 cloud_path 根目录
                        item_full_path = raw.get("path", "")
                        rel = self._calc_rel_path(item_full_path, cloud_path)
                        result = self._write_strm(strm_root, rel, name, pick_code, link_host)
                        if result == "created":
                            stats["created"] += 1
                        elif result == "skipped":
                            stats["skipped"] += 1
                        else:
                            stats["errors"] += 1
                logger.debug("[STRM遍历] iter_fs_files 共扫描 %d 项, stats=%s", scan_count, stats)
                return stats
            except ImportError:
                logger.debug("[STRM遍历] iter_fs_files 不可用，使用webapi回退")
            except Exception as e:
                logger.warning("[STRM遍历] iter_fs_files 出错，使用webapi回退: %s", e, exc_info=True)

        # ── 方案C：webapi 逐页列目录（p115client 完全不可用时）──────────────
        logger.debug("[STRM遍历] 使用webapi逐页列目录 cid=%s", cid)
        import asyncio as _asyncio
        loop = _asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                self._webapi_walk_and_write(
                    manager, cid, cloud_path, strm_root,
                    video_exts, link_host, from_time, stats,
                )
            )
        finally:
            loop.close()
        return stats

    def _calc_rel_path(self, item_full_path: str, cloud_path: str) -> Path:
        """
        计算文件相对于 cloud_path 根目录的相对路径（不含文件名）。
        例：cloud_path=/影音, item_full_path=/影音/电影/xxx.mkv → rel=电影
        """
        cloud_root = "/" + cloud_path.strip("/")
        full = "/" + item_full_path.strip("/")
        try:
            rel_str = Path(full).parent.relative_to(cloud_root)
        except ValueError:
            rel_str = Path(".")
        return Path(rel_str)

    def _write_strm(
        self, strm_root: Path, rel: Path,
        filename: str, pick_code: str, link_host: str,
    ) -> str:
        """
        写 .strm 文件。
        返回值：
          "created"  → 新建或内容变更，已写入
          "skipped"  → 文件已存在且内容相同，跳过
          "error"    → 写入失败
        """
        try:
            strm_dir = strm_root / rel
            strm_dir.mkdir(parents=True, exist_ok=True)
            strm_file = strm_dir / Path(filename).with_suffix(".strm").name
            strm_content = f"{link_host}/p115/play/{pick_code}/{filename}"
            if strm_file.exists():
                existing = strm_file.read_text(encoding="utf-8").strip()
                if existing == strm_content.strip():
                    logger.debug("[STRM跳过] 已存在且内容相同: %s", strm_file)
                    return "skipped"
                else:
                    logger.debug("[STRM更新] 内容变更，覆盖: %s\n  旧: %s\n  新: %s",
                                 strm_file, existing, strm_content)
            else:
                logger.debug("[STRM写入] 新建: %s", strm_file)
            strm_file.write_text(strm_content, encoding="utf-8")
            return "created"
        except Exception as e:
            logger.error("[STRM写入] 失败 %s: %s", filename, e)
            return "error"

    async def _webapi_walk_and_write(
        self,
        manager, cid: str, cloud_path: str,
        strm_root: Path, video_exts: set,
        link_host: str, from_time: int, stats: dict,
        depth: int = 0,
    ):
        """webapi 回退方案：递归列目录，带分页，遇到旧文件即停（增量模式）"""
        if depth > 30:
            return
        offset = 0
        page_size = 100
        while True:
            try:
                entries, total = await manager.adapter.list_files_paged(
                    cloud_path, cid=cid, offset=offset, limit=page_size,
                )
            except Exception as e:
                logger.error("[STRM遍历] webapi列目录失败 cid=%s: %s", cid, e)
                stats["errors"] += 1
                break

            logger.debug("[STRM遍历C] webapi cid=%s offset=%d 获取 %d/%d 条",
                         cid, offset, len(entries), total)

            stop_early = False
            sub_dirs = []
            for entry in entries:
                if entry.is_dir:
                    sub_dirs.append(entry)
                    continue
                ext = Path(entry.name).suffix.lstrip(".").lower()
                if ext not in video_exts:
                    logger.debug("[STRM遍历C] 跳过非视频文件: %s", entry.name)
                    stats["skipped"] += 1
                    continue
                item_mtime = int(entry.mtime or entry.ctime or 0)
                if from_time > 0 and item_mtime <= from_time:
                    logger.debug("[STRM遍历C] 跳过旧文件(mtime=%d <= from_time=%d): %s",
                                 item_mtime, from_time, entry.name)
                    # 115 按时间倒序，遇到旧文件说明后面都是旧的
                    stop_early = True
                    stats["skipped"] += 1
                    continue
                if not entry.pick_code:
                    logger.warning("[STRM遍历C] 文件缺少 pickcode，跳过: %s", entry.name)
                    stats["errors"] += 1
                    continue
                rel = self._calc_rel_path(entry.path, cloud_path)
                result = self._write_strm(strm_root, rel, entry.name, entry.pick_code, link_host)
                if result == "created":
                    stats["created"] += 1
                elif result == "skipped":
                    stats["skipped"] += 1
                else:
                    stats["errors"] += 1

            # 递归处理子目录
            for sub in sub_dirs:
                await self._webapi_walk_and_write(
                    manager, sub.file_id, sub.path,
                    strm_root, video_exts, link_host, from_time, stats, depth + 1,
                )

            offset += len(entries)
            if stop_early or offset >= total or len(entries) < page_size:
                break

    async def _resolve_cloud_cid(self, manager, cloud_path: str) -> str:
        """将云盘路径解析为 cid（目录 ID）"""
        cloud_path = cloud_path.strip().strip("/")
        if not cloud_path:
            return "0"
        # 优先用 p115client 直接调 fs_dir_getid 接口查目录 ID
        # 参考 p115strmhelper core/p115.py get_pid_by_path 的做法：
        #   resp = client.fs_dir_getid(path)
        #   return str(resp["id"])
        # 注意：p115client.tool.attr.get_id 返回 P115ID（继承 int），
        #       比较时有类型兼容问题，直接调 client.fs_dir_getid 更可靠。
        p115_client = manager.adapter._get_p115_client()
        if p115_client is not None:
            try:
                def _get_dir_id(path: str) -> str:
                    resp = p115_client.fs_dir_getid(path)
                    if resp.get("state") and resp.get("id") is not None:
                        return str(resp["id"])
                    raise ValueError(f"fs_dir_getid 返回异常: {resp}")
                cid = await asyncio.to_thread(_get_dir_id, "/" + cloud_path)
                logger.debug("[STRM同步] fs_dir_getid 解析 %r → cid=%s", cloud_path, cid)
                return cid
            except Exception as e:
                logger.debug("[STRM同步] p115client 路径解析失败，改用webapi: %s", e)
        # 回退：webapi 逐段查
        segments = [s for s in cloud_path.split("/") if s]
        cid = "0"
        current_path = ""
        for seg in segments:
            current_path = f"{current_path}/{seg}"
            try:
                entries, _ = await manager.adapter.list_files_paged(current_path, cid=cid, limit=200)
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

