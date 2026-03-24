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
        self._api_interval: float = 1.0   # API 请求间隔（秒），同步开始时从数据库读取

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

    @staticmethod
    async def _get_p115_settings() -> dict:
        """从数据库读取 115 高级设置（api_interval, api_concurrent 等）"""
        _defaults = {"api_interval": 1.0, "api_concurrent": 3}
        try:
            async with get_async_session_local() as db:
                result = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == "p115_settings")
                )
                cfg = result.scalars().first()
                if cfg and cfg.value:
                    saved = json.loads(cfg.value)
                    return {**_defaults, **saved}
        except Exception as e:
            logger.warning("读取 p115_settings 失败: %s", e)
        return _defaults

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
            # 读取 115 高级设置：API 请求间隔 + 并发线程数
            p115_settings = await self._get_p115_settings()
            api_interval = float(p115_settings.get("api_interval", 1.0))
            api_concurrent = int(p115_settings.get("api_concurrent", 3))
            logger.info("【全量STRM生成】API配置: interval=%.1fs, concurrent=%d", api_interval, api_concurrent)
            self._api_interval = api_interval
            # 覆盖模式：skip=跳过已存在, overwrite=覆盖已存在（对齐 p115strmhelper full_sync_overwrite_mode）
            overwrite_mode = config.get("full_overwrite_mode", "skip")

            logger.debug(
                "【全量STRM生成】配置快照: video_exts=%s link_host=%r url_tmpl=%r "
                "sync_pairs=%s overwrite_mode=%r",
                video_exts, link_host, url_tmpl, sync_pairs, overwrite_mode,
            )

            if not sync_pairs:
                logger.warning("【全量STRM生成】未配置同步路径对（请在STRM生成卡片中保存路径配置）")
                return

            for pair in sync_pairs:
                cloud_path = pair.get("cloud_path", "").strip()
                strm_root  = pair.get("strm_path", "").strip()
                if not cloud_path or not strm_root:
                    logger.debug("【全量STRM生成】跳过空路径对: cloud_path=%r strm_path=%r", cloud_path, strm_root)
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
                    api_interval=api_interval,
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

            # 读取 115 高级设置
            p115_settings = await self._get_p115_settings()
            api_interval = float(p115_settings.get("api_interval", 1.0))
            self._api_interval = api_interval

            if not sync_pairs:
                logger.warning("【增量STRM生成】未配置同步路径对（请在STRM生成卡片中保存路径配置）")
                return

            logger.debug(
                "【增量STRM生成】配置快照: last_sync_time=%d video_exts=%s link_host=%r sync_pairs=%s",
                last_sync_time, video_exts, link_host, sync_pairs,
            )

            for pair in sync_pairs:
                cloud_path = pair.get("cloud_path", "").strip()
                strm_root  = pair.get("strm_path", "").strip()
                if not cloud_path or not strm_root:
                    logger.debug("【增量STRM生成】跳过空路径对: cloud_path=%r strm_path=%r", cloud_path, strm_root)
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
                    api_interval=api_interval,
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

    # ── iOS UA（参考 p115strmhelper get_ios_ua_app，走 proapi.115.com 规避405风控）──
    _IOS_UA = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2_1 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
        "MicroMessenger/8.0.53(0x18003531) NetType/WIFI Language/zh_CN"
    )

    @classmethod
    def _ios_ua_kwargs(cls) -> dict:
        """
        返回 iOS UA + app="ios" 参数包。
        参考 p115strmhelper configer.get_ios_ua_app()：
          - headers user-agent 走 iOS UA，让 115 路由到 proapi.115.com 端点
          - app="ios" 告知 p115client 使用 iOS 专用接口（RSA加密直链接口）
        两者缺一不可：只改 UA 还会走 web 接口，只改 app 但 UA 是 web 会 405。
        """
        return {
            "headers": {"user-agent": cls._IOS_UA},
            "app": "ios",
        }

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
        api_interval: float = 1.0,
    ) -> dict:
        """
        遍历 115 目录树，对每个视频文件写 .strm。

        ⭐ 核心改造：参考 p115strmhelper，改用 iter_files_with_path_skim 替代 iterdir 递归：
          - iter_files_with_path_skim：单次迭代直接拿整棵树所有文件，内部自动处理分页和子目录
          - 每个 item 携带 item["path"] 完整云盘路径，无需我们自己拼路径
          - 搭配 iOS UA + app="ios" 规避 405 风控，走 proapi.115.com 端点
          - cooldown 控制分页间隔（p115strmhelper 用 1.5s，我们跟随用户 api_interval 配置）
          - 失败时回退到 iterdir 递归（老方案兜底）

        overwrite_mode: "skip"=跳过已存在, "overwrite"=覆盖已存在
        """
        stats = {"created": 0, "skipped": 0, "errors": 0}
        p115_client = manager.adapter._get_p115_client()

        if p115_client is None:
            logger.error("【全量STRM生成】p115_client 不可用，无法同步")
            return stats

        cloud_path_full = "/" + cloud_path.strip("/")
        scan_count = 0

        # DEBUG：打印函数入参快照
        logger.debug(
            "【全量STRM生成】_iter_and_write_strm 入参: cid=%r cloud_path=%r "
            "strm_root=%r from_time=%d overwrite_mode=%r api_interval=%.1f "
            "video_exts=%s p115_client_type=%s",
            cid, cloud_path, str(strm_root), from_time, overwrite_mode, api_interval,
            video_exts, type(p115_client).__name__,
        )

        # ── 尝试导入 iter_files_with_path_skim ────────────────────────────────
        try:
            from p115client.tool.iterdir import iter_files_with_path_skim, iterdir
            has_skim = True
            logger.debug("【全量STRM生成】iter_files_with_path_skim 导入成功，使用 skim 模式")
        except ImportError:
            try:
                from p115client.tool.iterdir import iterdir
                has_skim = False
                logger.debug("【全量STRM生成】iter_files_with_path_skim 不可用，降级到 iterdir 递归模式")
            except ImportError:
                logger.error("【全量STRM生成】p115client.tool.iterdir 不可用")
                return stats

        # ── _process_file：处理单个文件条目 ───────────────────────────────────
        def _process_file(item: dict, item_path: str):
            nonlocal scan_count
            scan_count += 1
            name       = item.get("name", "")
            pick_code  = item.get("pickcode") or item.get("pick_code") or item.get("pc", "")
            item_mtime = int(item.get("mtime") or item.get("utime") or item.get("t") or 0)

            logger.debug(
                "【全量STRM生成】处理条目 #%d: name=%r path=%r pickcode=%r mtime=%d keys=%s",
                scan_count, name, item_path, pick_code, item_mtime, list(item.keys()),
            )

            if from_time > 0 and item_mtime <= from_time:
                logger.debug(
                    "【全量STRM生成】跳过(mtime旧): %r mtime=%d <= from_time=%d",
                    name, item_mtime, from_time,
                )
                stats["skipped"] += 1
                return
            ext = Path(name).suffix.lstrip(".").lower()
            if ext not in video_exts:
                logger.debug("【全量STRM生成】跳过(非视频): %r ext=%r", name, ext)
                stats["skipped"] += 1
                return
            if not pick_code:
                logger.error("【全量STRM生成】%s 不存在 pickcode，跳过；item完整字段=%s", name, dict(item))
                stats["errors"] += 1
                return
            if not (len(pick_code) == 17 and pick_code.isalnum()):
                logger.error("【全量STRM生成】pickcode 格式错误 %r，跳过: %s", pick_code, name)
                stats["errors"] += 1
                return
            rel      = self._calc_rel_path(item_path, cloud_path)
            strm_url = self._render_strm_url(url_tmpl, link_host, pick_code, name, item_path)
            logger.debug(
                "【全量STRM生成】准备写STRM: name=%r rel=%r strm_url=%r",
                name, str(rel), strm_url,
            )
            result   = self._write_strm(strm_root, rel, name, strm_url, overwrite_mode)
            if result == "created":
                stats["created"] += 1
            elif result == "skipped":
                stats["skipped"] += 1
            else:
                stats["errors"] += 1

        # ══ 方案一：iter_files_with_path_skim（推荐，参考 p115strmhelper）═══════
        # 原理：p115client 内部一次拉整棵树，我们只消费迭代器输出
        #   - 不需要手动递归，不需要管子目录
        #   - 每个文件有 item["path"]（完整云盘绝对路径）直接使用
        #   - 风控最小：比 iterdir 递归少几十倍 API 调用
        #
        # ⚠️  iter_files_with_path_skim 实际签名（p115client 0.0.8.4.6）：
        #       iter_files_with_path_skim(client, cid=0, escape=True,
        #           with_ancestors=False, id_to_dirnode=None, path_already=False,
        #           max_workers=None, max_files=0, max_dirs=0, app='android',
        #           async_=False, **request_kwargs)
        #   - 没有 cooldown 参数！传 cooldown 会进入 **request_kwargs 导致请求失败
        #   - app 参数必须与 Cookie 类型（login_app）匹配，不能写死 "ios"
        #     web CK 传 "ios" → 用 iOS 接口但 Cookie 是 web → 115 返回空列表（不报错！）
        #   - headers(iOS UA) 只在非 web CK 时才需要传

        # 读取 login_app，决定 app 参数（必须与 Cookie 类型匹配）
        _WEB_APPS_SET = {"", "web", "desktop", "harmony"}
        login_app_raw = getattr(getattr(manager.adapter, "_auth", None), "login_app", "web") or "web"
        iter_app_for_skim = "web" if login_app_raw in _WEB_APPS_SET else login_app_raw

        logger.debug(
            "【全量STRM生成】Cookie 类型检测: login_app_raw=%r → iter_app_for_skim=%r",
            login_app_raw, iter_app_for_skim,
        )

        if has_skim:
            logger.info(
                "【全量STRM生成】使用 iter_files_with_path_skim 遍历 cid=%s cloud_path=%r "
                "app=%s overwrite=%s",
                cid, cloud_path, iter_app_for_skim, overwrite_mode,
            )
            try:
                iter_kwargs: dict = {
                    "cid": int(cid),
                    "app": iter_app_for_skim,   # 与 Cookie 类型匹配，不写死 "ios"
                }
                # 非 web CK（iOS/Android 等）才需要加对应 UA，避免 405 风控
                if iter_app_for_skim not in _WEB_APPS_SET:
                    iter_kwargs["headers"] = {"user-agent": self._IOS_UA}

                logger.debug(
                    "【全量STRM生成】iter_files_with_path_skim 调用参数: %s",
                    {k: v for k, v in iter_kwargs.items()},
                )

                _first_item_logged = False
                for item in iter_files_with_path_skim(p115_client, **iter_kwargs):
                    # 打印第一个 item 的完整字段，帮助确认数据结构
                    if not _first_item_logged:
                        logger.debug(
                            "【全量STRM生成】iter_files_with_path_skim 第一个 item 原始字段: %s",
                            dict(item),
                        )
                        _first_item_logged = True
                    # iter_files_with_path_skim 只返回文件，不返回目录
                    # 但保留 is_dir 检查作为防御性代码
                    if item.get("is_dir"):
                        logger.debug("【全量STRM生成】跳过目录 item: %r", item.get("name"))
                        continue
                    item_path = item.get("path", "")
                    if not item_path:
                        # 极少数情况下 path 缺失，用 name 兜底
                        name = item.get("name", "")
                        item_path = f"{cloud_path_full}/{name}"
                        logger.debug(
                            "【全量STRM生成】item 缺少 path 字段，用 name 兜底: %r → %r",
                            name, item_path,
                        )
                    _process_file(item, item_path)
                logger.info(
                    "【全量STRM生成】iter_files_with_path_skim 完成，扫描 %d 个文件，stats=%s",
                    scan_count, stats,
                )
                return stats
            except Exception as e:
                logger.warning(
                    "【全量STRM生成】iter_files_with_path_skim 失败: %s (type=%s)，"
                    "回退到 iterdir 递归方案", e, type(e).__name__,
                    exc_info=True,
                )
                # 重置 stats，用旧方案重跑
                stats = {"created": 0, "skipped": 0, "errors": 0}
                scan_count = 0

        # ══ 方案二：iterdir 递归（兜底，CK 类型不支持 skim 时使用）════════════
        # 根据 login_app 动态选择接口（Web CK 用 web，iOS CK 用 ios）
        login_app = getattr(getattr(manager.adapter, "_auth", None), "login_app", "web") or "web"
        _WEB_APPS = {"", "web", "desktop", "harmony"}
        iter_app  = "web" if login_app in _WEB_APPS else login_app
        logger.info(
            "【全量STRM生成】使用 iterdir 递归遍历 cid=%s cloud_path=%r iter_app=%s overwrite=%s",
            cid, cloud_path, iter_app, overwrite_mode,
        )

        def _walk(walk_cid: int, walk_path: str, depth: int = 0):
            nonlocal scan_count
            if depth > 50:
                logger.warning("【全量STRM生成】目录层级超过50层，停止: %s", walk_path)
                return
            logger.debug("【全量STRM生成】iterdir 递归进入: cid=%d path=%r depth=%d", walk_cid, walk_path, depth)
            items = None
            for attempt in range(3):
                try:
                    items = list(iterdir(client=p115_client, cid=walk_cid,
                                         cooldown=api_interval, app=iter_app))
                    logger.debug("【全量STRM生成】iterdir cid=%d 返回 %d 条目", walk_cid, len(items))
                    break
                except Exception as e:
                    err_str = str(e) or repr(e)
                    if attempt < 2:
                        wait = 5 * (attempt + 1)
                        logger.warning(
                            "【全量STRM生成】iterdir 失败(重试%d/3) path=%s: %s，%ds后重试",
                            attempt + 1, walk_path, err_str, wait,
                        )
                        time.sleep(wait)
                    else:
                        logger.error("【全量STRM生成】iterdir 失败(重试耗尽) path=%s: %s", walk_path, err_str)
                        stats["errors"] += 1
                        return
            if items is None:
                return
            sub_dirs = []
            for item in items:
                name = item.get("name", "")
                if not name:
                    continue
                item_path = f"{walk_path}/{name}"
                if item.get("is_dir"):
                    sub_cid = int(item.get("id") or item.get("file_id") or 0)
                    if sub_cid:
                        sub_dirs.append((sub_cid, item_path))
                        logger.debug("【全量STRM生成】发现子目录: %r cid=%d", item_path, sub_cid)
                else:
                    _process_file(item, item_path)
            for idx, (sub_cid, sub_path) in enumerate(sub_dirs):
                if idx > 0:
                    time.sleep(api_interval)
                _walk(sub_cid, sub_path, depth + 1)

        _walk(int(cid), cloud_path_full)
        logger.info("【全量STRM生成】iterdir 递归完成，扫描 %d 个文件，stats=%s", scan_count, stats)
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
            # 带重试的列目录（参考 p115strmhelper: 3 次重试 + 退避）
            entries = None
            total = 0
            for attempt in range(3):
                try:
                    entries, total = await manager.adapter.list_files_paged(
                        cloud_path, cid=cid, offset=offset, limit=page_size,
                    )
                    break
                except Exception as e:
                    if attempt < 2:
                        wait = 5 * (attempt + 1)
                        logger.warning(
                            "【全量STRM生成】webapi列目录失败(重试%d/3) cid=%s: %s，%ds后重试",
                            attempt + 1, cid, e, wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error("【全量STRM生成】webapi列目录失败(重试耗尽) cid=%s: %s", cid, e)
                        stats["errors"] += 1

            if entries is None:
                break  # 3 次都失败，跳出翻页循环

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
            for idx, sub in enumerate(sub_dirs):
                if idx > 0:
                    await asyncio.sleep(self._api_interval)
                await self._webapi_walk_and_write(
                    manager, sub.file_id, sub.path,
                    strm_root, video_exts, link_host, url_tmpl, from_time, stats, overwrite_mode, depth + 1,
                )

            offset += len(entries)
            if stop_early or offset >= total or len(entries) < page_size:
                break
            await asyncio.sleep(self._api_interval)

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

        logger.debug(
            "【全量STRM生成】_resolve_cloud_cid: cloud_path=%r login_app=%r iter_app=%r p115_client=%s",
            cloud_path, login_app, iter_app,
            type(p115_client).__name__ if p115_client else "None",
        )

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
                        logger.debug(
                            "【全量STRM生成】iterdir 查找路径段 %r (parent_cid=%d, app=%s)",
                            seg, cid, iter_app,
                        )
                        dir_items = list(iterdir(
                            client=p115_client,
                            cid=cid,
                            cooldown=1,
                            app=iter_app,
                        ))
                        logger.debug(
                            "【全量STRM生成】iterdir cid=%d 返回 %d 条目，查找 %r",
                            cid, len(dir_items), seg,
                        )
                        for item in dir_items:
                            if item.get("is_dir") and item.get("name") == seg:
                                found = item
                                break
                        if found is None:
                            dir_names = [i.get("name") for i in dir_items if i.get("is_dir")]
                            logger.debug(
                                "【全量STRM生成】路径段 %r 未找到，当前层目录列表: %s",
                                seg, dir_names,
                            )
                            raise ValueError(f"路径段未找到: {seg!r} (parent_cid={cid})")
                        cid = int(found.get("id") or found.get("file_id") or 0)
                        logger.debug("【全量STRM生成】路径段 %r 找到, cid=%d", seg, cid)
                    return str(cid)

                segments = [s for s in cloud_path.split("/") if s]
                logger.debug("【全量STRM生成】开始 iterdir 逐级解析: segments=%s", segments)
                cid = await asyncio.to_thread(_resolve_by_iterdir, segments)
                logger.info("【全量STRM生成】iterdir 逐级解析 %r → cid=%s (app=%s)",
                            cloud_path, cid, iter_app)
                return cid
            except ImportError:
                logger.warning("【全量STRM生成】iterdir 不可用（ImportError），尝试 fs_dir_getid")
            except Exception as e:
                logger.warning("【全量STRM生成】iterdir 路径解析失败: %s (type=%s)，尝试备用方案",
                               e, type(e).__name__, exc_info=True)

        # ── 方案B：fs_dir_getid（仅 web CK，iOS/Android 会 405）───────────
        if p115_client is not None and iter_app == "web":
            try:
                logger.debug("【全量STRM生成】尝试方案B fs_dir_getid: path=%r", "/" + cloud_path)
                def _get_dir_id(path: str) -> str:
                    resp = p115_client.fs_dir_getid(path)
                    logger.debug("【全量STRM生成】fs_dir_getid 原始响应: %s", resp)
                    if resp.get("state") and resp.get("id") is not None:
                        return str(resp["id"])
                    raise ValueError(f"fs_dir_getid 返回异常: {resp}")
                cid = await asyncio.to_thread(_get_dir_id, "/" + cloud_path)
                logger.debug("【全量STRM生成】方案B fs_dir_getid 解析 %r → cid=%s", cloud_path, cid)
                return cid
            except Exception as e:
                logger.debug("【全量STRM生成】方案B fs_dir_getid 失败，改用方案C webapi: %s", e)

        # ── 方案C：webapi list_files_paged 逐段（最终兜底）────────────────
        logger.debug("【全量STRM生成】使用方案C: webapi list_files_paged 逐段解析 %r", cloud_path)
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
                    logger.debug("【全量STRM生成】方案C: 路径段 %r 找到 cid=%s", seg, cid)
                else:
                    logger.warning("【全量STRM生成】路径段未找到: %s (parent_cid=%s)", seg, cid)
                    return ""
            except Exception as e:
                logger.error("【全量STRM生成】解析路径失败 %s: %s", current_path, e)
                return ""
        return cid

