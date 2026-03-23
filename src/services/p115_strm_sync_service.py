# src/services/p115_strm_sync_service.py
# 115 STRM 全量/增量生成服务
#

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
        """获取 STRM 链接地址（优先配置项，回退 external_url / go_port）"""
        host = config.get("strm_link_host", "").strip().rstrip("/")
        if not host:
            from src.core.config import settings
            host = (settings.server.external_url or "").rstrip("/")
        if not host:
            from src.core.config import settings
            host = f"http://127.0.0.1:{settings.server.go_port}"
        return host

    @staticmethod
    async def _get_url_template() -> str:
        """从数据库异步读取用户配置的 STRM URL 模板（key=strm_url_template）"""
        import json as _json
        try:
            from src.db import get_async_session_local
            from src.db.models.system import SystemConfig
            from sqlalchemy import select
            async with get_async_session_local() as db:
                row = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == "strm_url_template")
                )
                cfg = row.scalars().first()
                if cfg and cfg.value:
                    return _json.loads(cfg.value)
        except Exception as e:
            logger.debug("【全量STRM生成】读取URL模板失败: %s", e)
        return ""

    @staticmethod
    def _render_strm_url(
        tmpl_str: str,
        link_host: str,
        pick_code: str,
        file_name: str,
        file_path: str = "",
        sha1: str = "",
    ) -> str:
        """
        渲染 STRM URL 模板（纯标准库实现，不依赖 jinja2）。

        支持的模板语法（对齐 p115strmhelper StrmUrlTemplateResolver 过滤器）：
          {{ base_url }}               → link_host（如 http://127.0.0.1:9906）
          {{ pickcode }}               → pick_code
          {{ file_name }}              → 文件名（含扩展名）
          {{ file_path }}              → 云盘完整路径（如 /影音/电影/xxx.mkv）
          {{ sha1 }}                   → 文件 sha1（可能为空）
          {{ file_name | urlencode }}  → URL 编码（不保留斜杠）
          {{ file_path | urlencode }}  → URL 编码（不保留斜杠）
          {{ file_path | path_encode }}→ URL 编码（保留斜杠，对齐 p115strmhelper path_encode）
          {{ file_name | upper }}      → 转大写
          {{ file_name | lower }}      → 转小写

        若模板为空或渲染失败，回退到默认格式：
          {link_host}/p115/play/{pick_code}/{file_name}
        """
        import re
        from urllib.parse import quote as _url_quote

        default_url = f"{link_host}/p115/play/{pick_code}/{file_name}"
        if not tmpl_str:
            return default_url
        try:
            variables = {
                "base_url":  link_host,
                "pickcode":  pick_code,
                "file_name": file_name,
                "file_path": file_path,
                "sha1":      sha1,
            }

            def _replace(m: re.Match) -> str:
                expr = m.group(1).strip()
                # 支持 {{ var | filter }} 过滤器（对齐 p115strmhelper 注册的过滤器）
                if "|" in expr:
                    parts = [p.strip() for p in expr.split("|", 1)]
                    var_name, filt = parts[0], parts[1]
                    val = str(variables.get(var_name, ""))
                    if filt == "urlencode":
                        return _url_quote(val, safe="")
                    if filt == "path_encode":
                        # 路径编码过滤器：保留斜杠（对齐 p115strmhelper path_encode_filter）
                        return _url_quote(val, safe="/")
                    if filt == "upper":
                        return val.upper()
                    if filt == "lower":
                        return val.lower()
                    return val
                return str(variables.get(expr, ""))

            rendered = re.sub(r"\{\{\s*(.*?)\s*\}\}", _replace, tmpl_str)
            return rendered.strip()
        except Exception as e:
            logger.warning("【全量STRM生成】模板渲染失败，使用默认格式: %s", e)
            return default_url

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
                logger.warning("【全量STRM生成】115 未启用或未就绪")
                return

            video_exts = self._get_video_exts(config)
            link_host  = self._get_link_host(config)
            url_tmpl   = await self._get_url_template()
            sync_pairs = self._resolve_sync_pairs(config, "full")
            # 覆盖模式：skip=跳过已存在, overwrite=覆盖已存在（对齐 p115strmhelper full_sync_overwrite_mode）
            overwrite_mode = config.get("full_overwrite_mode", "skip")

            if not sync_pairs:
                logger.warning("【全量STRM生成】未配置同步路径对（请在STRM生成卡片中保存路径配置）")
                return

            for pair in sync_pairs:
                cloud_path = pair.get("cloud_path", "").strip()
                strm_root  = pair.get("strm_path", "").strip()
                if not cloud_path or not strm_root:
                    continue
                start_cid = await self._resolve_cloud_cid(manager, cloud_path)
                if not start_cid:
                    logger.warning("【全量STRM生成】网盘媒体目录 ID 获取失败，跳过: %s", cloud_path)
                    continue
                logger.info("【全量STRM生成】网盘媒体目录 ID 获取成功: %s (cid=%s) → %s，覆盖模式: %s",
                            cloud_path, start_cid, strm_root, overwrite_mode)
                pair_stats = await asyncio.to_thread(
                    self._iter_and_write_strm,
                    manager, start_cid, cloud_path,
                    Path(strm_root), video_exts, link_host, url_tmpl,
                    from_time=0,
                    overwrite_mode=overwrite_mode,
                )
                for k in stats:
                    stats[k] += pair_stats.get(k, 0)
                self._progress = {"stage": "scanning", **stats}

        except Exception as e:
            logger.error("【全量STRM生成】全量生成 STRM 文件失败: %s", e, exc_info=True)
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
            logger.info("【全量STRM生成】全量生成 STRM 文件完成，总共生成 %d 个 STRM 文件，耗时 %.1fs，stats=%s",
                        stats.get("created", 0), elapsed, stats)

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
                logger.warning("【增量STRM生成】115 未启用或未就绪")
                return

            video_exts = self._get_video_exts(config)
            link_host  = self._get_link_host(config)
            url_tmpl   = await self._get_url_template()
            sync_pairs = self._resolve_sync_pairs(config, "inc")

            if not sync_pairs:
                logger.warning("【增量STRM生成】未配置同步路径对（请在STRM生成卡片中保存路径配置）")
                return

            for pair in sync_pairs:
                cloud_path = pair.get("cloud_path", "").strip()
                strm_root  = pair.get("strm_path", "").strip()
                if not cloud_path or not strm_root:
                    continue
                start_cid = await self._resolve_cloud_cid(manager, cloud_path)
                if not start_cid:
                    logger.warning("【增量STRM生成】网盘媒体目录 ID 获取失败，跳过: %s", cloud_path)
                    continue
                logger.info(
                    "【增量STRM生成】网盘媒体目录 ID 获取成功(last_sync=%d): %s (cid=%s) → %s",
                    last_sync_time, cloud_path, start_cid, strm_root,
                )
                pair_stats = await asyncio.to_thread(
                    self._iter_and_write_strm,
                    manager, start_cid, cloud_path,
                    Path(strm_root), video_exts, link_host, url_tmpl,
                    from_time=last_sync_time,
                )
                # 注意：增量同步固定 overwrite_mode="skip"（只处理新增文件，不覆盖已有）
                for k in stats:
                    stats[k] += pair_stats.get(k, 0)
                self._progress = {"stage": "scanning", **stats}

        except Exception as e:
            logger.error("【增量STRM生成】增量生成 STRM 文件失败: %s", e, exc_info=True)
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
            logger.info("【增量STRM生成】增量生成 STRM 文件完成，总共生成 %d 个 STRM 文件，耗时 %.1fs，stats=%s",
                        stats.get("created", 0), elapsed, stats)

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
        url_tmpl: str = "",
        from_time: int = 0,
        overwrite_mode: str = "skip",
    ) -> dict:
        """
        遍历 115 目录树（递归），对每个视频文件写 .strm。

        使用 iterdir 手动递归遍历整棵目录树，自己维护完整路径：
          - iterdir 只列当前目录一层（无递归），但结构简单、兼容所有 CK 类型
          - 每层目录遍历后，对子目录递归调用，拼接路径
          - 完整路径由我们自己构建，不依赖接口返回的 path 字段
          - cooldown=1s 避免频率限制

        overwrite_mode: "skip"=跳过已存在, "overwrite"=覆盖已存在
        """
        stats = {"created": 0, "skipped": 0, "errors": 0}
        p115_client = manager.adapter._get_p115_client()

        if p115_client is None:
            logger.error("【全量STRM生成】p115_client 不可用，无法同步")
            return stats

        # 根据 login_app 动态选择接口（避免 CK 类型不匹配导致 405 风控）
        login_app = getattr(getattr(manager.adapter, "_auth", None), "login_app", "web") or "web"
        _WEB_APPS = {"", "web", "desktop", "harmony"}
        iter_app = "web" if login_app in _WEB_APPS else login_app
        logger.info("【全量STRM生成】开始遍历 cid=%s cloud_path=%r iter_app=%s overwrite=%s",
                    cid, cloud_path, iter_app, overwrite_mode)

        # cloud_path_full：遍历根的完整云盘路径，用于拼接子路径
        cloud_path_full = "/" + cloud_path.strip("/")
        scan_count = 0

        try:
            from p115client.tool.iterdir import iterdir
        except ImportError:
            logger.error("【全量STRM生成】p115client.tool.iterdir 不可用")
            return stats

        def _process_file(item: dict, item_path: str):
            """处理单个文件条目，写 STRM，更新 stats"""
            nonlocal scan_count
            scan_count += 1
            name      = item.get("name", "")
            pick_code = item.get("pickcode") or item.get("pick_code") or item.get("pc", "")
            item_mtime = int(item.get("mtime") or item.get("utime") or item.get("t") or 0)

            if from_time > 0 and item_mtime <= from_time:
                logger.debug("【全量STRM生成】跳过旧文件(mtime=%d <= from_time=%d): %s",
                             item_mtime, from_time, name)
                stats["skipped"] += 1
                return
            ext = Path(name).suffix.lstrip(".").lower()
            if ext not in video_exts:
                logger.debug("【全量STRM生成】跳过非视频文件: %s", name)
                stats["skipped"] += 1
                return
            if not pick_code:
                logger.error("【全量STRM生成】%s 不存在 pickcode 值，无法生成 STRM 文件", name)
                stats["errors"] += 1
                return
            # 参考 p115strmhelper：pickcode 必须是 17 位纯字母数字
            if not (len(pick_code) == 17 and pick_code.isalnum()):
                logger.error("【全量STRM生成】错误的 pickcode 值 %r，跳过: %s", pick_code, name)
                stats["errors"] += 1
                return
            rel      = self._calc_rel_path(item_path, cloud_path)
            strm_url = self._render_strm_url(url_tmpl, link_host, pick_code, name, item_path)
            result   = self._write_strm(strm_root, rel, name, strm_url, overwrite_mode)
            if result == "created":
                stats["created"] += 1
            elif result == "skipped":
                stats["skipped"] += 1
            else:
                stats["errors"] += 1

        def _walk(walk_cid: int, walk_path: str, depth: int = 0):
            """递归遍历：iterdir 列当前层，文件直接处理，目录递归进入"""
            if depth > 50:
                logger.warning("【全量STRM生成】目录层级超过50层，停止递归: %s", walk_path)
                return
            try:
                items = list(iterdir(client=p115_client, cid=walk_cid,
                                     cooldown=1, app=iter_app))
            except Exception as e:
                logger.warning("【全量STRM生成】iterdir 失败 cid=%s path=%s: %s",
                               walk_cid, walk_path, e)
                return

            sub_dirs = []
            for item in items:
                name     = item.get("name", "")
                if not name:
                    continue
                item_path = f"{walk_path}/{name}"
                if item.get("is_dir"):
                    sub_cid = int(item.get("id") or item.get("file_id") or 0)
                    if sub_cid:
                        sub_dirs.append((sub_cid, item_path))
                else:
                    _process_file(item, item_path)

            # 先处理完当前层文件，再递归子目录（BFS 风格，便于调试）
            for sub_cid, sub_path in sub_dirs:
                logger.debug("【全量STRM生成】进入子目录: %s (cid=%s)", sub_path, sub_cid)
                _walk(sub_cid, sub_path, depth + 1)

        _walk(int(cid), cloud_path_full)
        logger.info("【全量STRM生成】iterdir 递归遍历完成，共扫描 %d 个文件，stats=%s",
                    scan_count, stats)
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
        filename: str, strm_url: str,
        overwrite_mode: str = "skip",
    ) -> str:
        """
        写 .strm 文件。
        overwrite_mode:
          "skip"      → 文件已存在时跳过（默认，对齐 p115strmhelper overwrite_mode=never）
          "overwrite" → 文件已存在时强制覆盖（对齐 p115strmhelper overwrite_mode=always）
        返回值：
          "created"  → 新建或覆盖写入
          "skipped"  → 文件已存在且跳过
          "error"    → 写入失败
        """
        try:
            strm_dir = strm_root / rel
            strm_dir.mkdir(parents=True, exist_ok=True)
            # 参考 p115strmhelper StrmGenerater.get_strm_filename：
            # .iso 文件保留扩展名 → stem.iso.strm；其他文件 → stem.strm
            _suffix = Path(filename).suffix.lower()
            _stem   = Path(filename).stem
            strm_name = f"{_stem}.iso.strm" if _suffix == ".iso" else f"{_stem}.strm"
            strm_file = strm_dir / strm_name
            strm_content = strm_url
            if strm_file.exists():
                existing = strm_file.read_text(encoding="utf-8").strip()
                if existing == strm_content.strip():
                    logger.debug("【全量STRM生成】STRM 文件已存在且内容相同，跳过: %s", strm_file)
                    return "skipped"
                if overwrite_mode == "skip":
                    # 对齐 p115strmhelper overwrite_mode=never
                    logger.debug("【全量STRM生成】STRM 文件 %s 已存在，覆盖模式 skip，跳过此路径", strm_file)
                    return "skipped"
                # overwrite_mode == "overwrite"
                logger.debug("【全量STRM生成】STRM 文件内容变更，覆盖: %s", strm_file)
            else:
                logger.debug("【全量STRM生成】新建 STRM 文件: %s → %s", strm_file, strm_content)
            strm_file.write_text(strm_content, encoding="utf-8")
            # 对齐 p115strmhelper 日志格式
            logger.info("【全量STRM生成】生成 STRM 文件成功: %s", str(strm_file))
            return "created"
        except Exception as e:
            logger.error("【全量STRM生成】写入 STRM 文件失败: %s  %s", filename, e)
            return "error"

    async def _webapi_walk_and_write(
        self,
        manager, cid: str, cloud_path: str,
        strm_root: Path, video_exts: set,
        link_host: str, url_tmpl: str, from_time: int, stats: dict,
        overwrite_mode: str = "skip",
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
                logger.error("【全量STRM生成】webapi列目录失败 cid=%s: %s", cid, e)
                stats["errors"] += 1
                break

            logger.debug("【全量STRM生成】webapi cid=%s offset=%d 获取 %d/%d 条",
                         cid, offset, len(entries), total)

            stop_early = False
            sub_dirs = []
            for entry in entries:
                if entry.is_dir:
                    sub_dirs.append(entry)
                    continue
                ext = Path(entry.name).suffix.lstrip(".").lower()
                if ext not in video_exts:
                    logger.debug("【全量STRM生成】跳过非视频文件: %s", entry.name)
                    stats["skipped"] += 1
                    continue
                item_mtime = int(entry.mtime or entry.ctime or 0)
                if from_time > 0 and item_mtime <= from_time:
                    logger.debug("【全量STRM生成】跳过旧文件(mtime=%d <= from_time=%d): %s",
                                 item_mtime, from_time, entry.name)
                    stop_early = True
                    stats["skipped"] += 1
                    continue
                if not entry.pick_code:
                    logger.error("【全量STRM生成】%s 不存在 pickcode 值，无法生成 STRM 文件", entry.name)
                    stats["errors"] += 1
                    continue
                rel = self._calc_rel_path(entry.path, cloud_path)
                strm_url = self._render_strm_url(url_tmpl, link_host, entry.pick_code, entry.name, entry.path)
                result = self._write_strm(strm_root, rel, entry.name, strm_url, overwrite_mode)
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
                    strm_root, video_exts, link_host, url_tmpl, from_time, stats, overwrite_mode, depth + 1,
                )

            offset += len(entries)
            if stop_early or offset >= total or len(entries) < page_size:
                break

    async def _resolve_cloud_cid(self, manager, cloud_path: str) -> str:
        """将云盘路径解析为 cid（目录 ID）。

        方案A（首选）：iterdir 逐级遍历
          - 走 iter_app 对应接口，兼容所有 CK 类型
          - iOS/Android CK 下不触发 405（fs_dir_getid 的根本问题所在）
          - 参考 p115strmhelper core/p115.py get_pid_by_path 的实现思路

        方案B（兜底，仅 web CK）：fs_dir_getid
          - webapi.115.com/files/getid，仅 web CK 可用，iOS/Android 会 405

        方案C（最终兜底）：webapi list_files_paged 逐段查
        """
        cloud_path = cloud_path.strip().strip("/")
        if not cloud_path:
            return "0"

        p115_client = manager.adapter._get_p115_client()

        # 读取 login_app，决定接口（对齐 _iter_and_write_strm 的 iter_app 逻辑）
        login_app = getattr(getattr(manager.adapter, "_auth", None), "login_app", "web") or "web"
        _WEB_APPS = {"", "web", "desktop", "harmony"}
        iter_app = "web" if login_app in _WEB_APPS else login_app

        # ── 方案A：iterdir 逐级遍历（参考 p115strmhelper get_pid_by_path）───
        # 核心修复：fs_dir_getid 调用 webapi.115.com/files/getid，
        # iOS/Android CK 对该接口返回 405 Method Not Allowed，
        # 改为 iterdir 按目录层级依次查找，走 iter_app 对应接口，无 405 问题。
        if p115_client is not None:
            try:
                from p115client.tool.iterdir import iterdir

                def _resolve_by_iterdir(segments: list) -> str:
                    cid = 0
                    for seg in segments:
                        found = None
                        for item in iterdir(
                            client=p115_client,
                            cid=cid,
                            cooldown=1,
                            app=iter_app,
                        ):
                            if item.get("is_dir") and item.get("name") == seg:
                                found = item
                                break
                        if found is None:
                            raise ValueError(f"路径段未找到: {seg!r} (parent_cid={cid})")
                        cid = int(found.get("id") or found.get("file_id") or 0)
                    return str(cid)

                segments = [s for s in cloud_path.split("/") if s]
                cid = await asyncio.to_thread(_resolve_by_iterdir, segments)
                logger.debug("【全量STRM生成】iterdir 逐级解析 %r → cid=%s (app=%s)",
                             cloud_path, cid, iter_app)
                return cid
            except ImportError:
                logger.debug("【全量STRM生成】iterdir 不可用，尝试 fs_dir_getid")
            except Exception as e:
                logger.warning("【全量STRM生成】iterdir 路径解析失败: %s，尝试备用方案", e)

        # ── 方案B：fs_dir_getid（仅 web CK，iOS/Android 会 405）───────────
        if p115_client is not None and iter_app == "web":
            try:
                def _get_dir_id(path: str) -> str:
                    resp = p115_client.fs_dir_getid(path)
                    if resp.get("state") and resp.get("id") is not None:
                        return str(resp["id"])
                    raise ValueError(f"fs_dir_getid 返回异常: {resp}")
                cid = await asyncio.to_thread(_get_dir_id, "/" + cloud_path)
                logger.debug("【全量STRM生成】fs_dir_getid 解析 %r → cid=%s", cloud_path, cid)
                return cid
            except Exception as e:
                logger.debug("【全量STRM生成】fs_dir_getid 路径解析失败，改用webapi: %s", e)

        # ── 方案C：webapi list_files_paged 逐段（最终兜底）────────────────
        segments = [s for s in cloud_path.split("/") if s]
        cid = "0"
        current_path = ""
        for seg in segments:
            current_path = f"{current_path}/{seg}"
            try:
                entries, _ = await manager.adapter.list_files_paged(
                    current_path, cid=cid, limit=200)
                found = next((e for e in entries if e.is_dir and e.name == seg), None)
                if found:
                    cid = found.file_id
                else:
                    logger.warning("【全量STRM生成】路径段未找到: %s (parent_cid=%s)", seg, cid)
                    return ""
            except Exception as e:
                logger.error("【全量STRM生成】解析路径失败 %s: %s", current_path, e)
                return ""
        return cid

