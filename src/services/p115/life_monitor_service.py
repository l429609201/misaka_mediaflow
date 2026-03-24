# src/services/p115/life_monitor_service.py
# 115 生活事件监控服务
#
# 接口选择（根据扫码时 login_app）：
#   web/desktop/harmony CK → life_list(app="web")  → life.115.com ✅
#   android/ios/alipaymini → iter_life_behavior_once(app=login_app) ✅
#
# 流控（对齐 p115strmhelper once_pull）：
#   cooldown=4s；失败重试 3 次，间隔 2s；无新事件等 20s；出错等 30s

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from src.services.p115.modules import (
    load_monitor_config, save_monitor_config,
    get_video_exts, get_link_host,
    get_url_template, render_strm_url, write_strm, calc_rel_path,
    save_fscache_and_strmfile,
)

logger = logging.getLogger(__name__)

# 需要触发 STRM 操作的事件类型（对齐 p115strmhelper _SYNC_TRIGGER_TYPES）
_SYNC_TRIGGER_TYPES = {1, 2, 5, 6, 14, 17, 18, 22}
# 仅需触发增量同步（目录操作）的类型
_DIR_OP_TYPES = {17, 18}

# 事件类型中文名
_BEHAVIOR_TYPE_NAMES = {
    1: "上传图片", 2: "上传文件/目录", 3: "标星图片", 4: "标星文件/目录",
    5: "移动图片", 6: "移动文件/目录", 7: "浏览图片", 8: "浏览视频",
    9: "搜索", 10: "删除图片", 11: "分享", 12: "下载", 13: "打开",
    14: "接收文件", 15: "设置标签", 16: "内容审核", 17: "创建新目录",
    18: "复制文件夹", 19: "浏览文件", 20: "上传目录", 21: "解压缩",
    22: "删除文件/文件夹",
}

# behavior_type 字符串 → int（life_list webapi 返回字符串）
_BEHAVIOR_STR_TO_INT = {
    "upload_image": 1, "upload_file": 2, "star_image": 3, "star_file": 4,
    "move_image": 5, "move_file": 6, "browse_image": 7, "browse_video": 8,
    "search": 9, "delete_image": 10, "share": 11, "download": 12,
    "open": 13, "receive_file": 14, "set_label": 15, "audit": 16,
    "create_folder": 17, "copy_folder": 18, "browse_file": 19,
    "upload_folder": 20, "decompress": 21, "delete_file": 22,
}


def _get_manager():
    from src.adapters.storage.p115 import P115Manager
    return P115Manager()


def _parse_behavior_type(raw) -> int:
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        if raw.isdigit():
            return int(raw)
        return _BEHAVIOR_STR_TO_INT.get(raw, -1)
    return -1


def _parse_event_fields(raw: dict, raw_count: int) -> Optional[dict]:
    """从原始事件 dict 解析标准化字段，返回 None 表示不需要处理"""
    logger.debug("【监控生活事件】原始事件 #%d data=%s", raw_count, raw)

    raw_type = raw.get("type") or raw.get("behavior_type")
    ev_type  = _parse_behavior_type(raw_type)
    ev_name  = _BEHAVIOR_TYPE_NAMES.get(ev_type, f"未知({ev_type})")

    if ev_type not in _SYNC_TRIGGER_TYPES:
        logger.debug("【监控生活事件】忽略事件类型 %s(%d)", ev_name, ev_type)
        return None

    # 兼容 iter_life_behavior_once 和 life_list 两种字段结构
    file_info = raw.get("file_info") or {}
    file_name = (raw.get("file_name") or file_info.get("file_name") or
                 raw.get("name") or "").strip()
    file_id   = str(raw.get("file_id") or file_info.get("file_id") or raw.get("fid") or "")
    parent_id = str(raw.get("parent_id") or file_info.get("parent_id") or raw.get("pid") or "")
    pick_code = raw.get("pick_code") or file_info.get("pick_code") or raw.get("pc") or ""
    file_category = int(raw.get("file_category", -1))
    event_id  = int(raw.get("id") or raw.get("event_id") or 0)
    ev_time   = int(raw.get("update_time") or raw.get("time") or time.time())

    logger.info("【监控生活事件】%s: file=%r file_id=%s pick=%s", ev_name, file_name, file_id, pick_code)

    return {
        "type":          ev_type,
        "type_name":     ev_name,
        "file_name":     file_name,
        "file_id":       file_id,
        "parent_id":     parent_id,
        "pick_code":     pick_code,
        "file_category": file_category,
        "event_id":      event_id,
        "time":          ev_time,
    }


def _fetch_via_life_list(p115_client, from_time: int, from_id: int, _time) -> Optional[list]:
    """web CK 专用：POST /behavior/list 拉取生活事件"""
    events = []
    raw_count = 0
    try:
        import time as _t
        payload = {
            "start":        0,
            "limit":        100,
            "type":         0,
            "show_note_cal": 0,
            "show_note_todo": 0,
            "show_note_done": 0,
            "start_time":   from_time,
            "end_time":     int(_t.time()),
        }
        resp = p115_client.life_list(payload)
        logger.debug("【监控生活事件】life_list 响应: state=%s count=%s",
                     resp.get("state"), resp.get("count"))
        if not resp.get("state"):
            logger.warning("【监控生活事件】life_list 返回失败: %s", resp)
            return None

        items = resp.get("data", {}).get("list", [])
        for item in items:
            raw_count += 1
            parsed = _parse_event_fields(item, raw_count)
            if parsed is not None:
                events.append(parsed)
        logger.debug("【监控生活事件】life_list 完毕: 原始%d条 触发%d条", raw_count, len(events))
        return events
    except Exception as e:
        logger.warning("【监控生活事件】life_list 异常: %s", e, exc_info=True)
        return None


def _fetch_via_behavior_once(p115_client, from_time: int, from_id: int,
                              login_app: str, _time) -> Optional[list]:
    """非 web CK 专用：iter_life_behavior_once(app=login_app)"""
    try:
        from p115client.tool.life import iter_life_behavior_once
    except ImportError:
        return _fetch_via_life_list(p115_client, from_time, from_id, _time)
    events = []
    raw_count = 0
    try:
        for event in iter_life_behavior_once(
            client=p115_client, from_time=from_time,
            from_id=from_id, cooldown=4, app=login_app,
        ):
            raw_count += 1
            parsed = _parse_event_fields(event, raw_count)
            if parsed is not None:
                events.append(parsed)
        return events
    except Exception as e:
        logger.warning("【监控生活事件】behavior_once(app=%s) 异常: %s", login_app, e, exc_info=True)
        return None


def _sync_fetch_life_events(p115_client, from_time: int, from_id: int, login_app: str) -> Optional[list]:
    import time as _t
    _WEB_APPS = {"", "web", "desktop", "harmony"}
    if login_app in _WEB_APPS:
        return _fetch_via_life_list(p115_client, from_time, from_id, _t)
    return _fetch_via_behavior_once(p115_client, from_time, from_id, login_app, _t)


def _sync_get_parent_path(p115_client, parent_id: str) -> str:
    """通过 parent_id 查询父目录路径"""
    if not p115_client or not parent_id or parent_id == "0":
        return ""
    try:
        resp = p115_client.fs_info({"file_id": int(parent_id)})
        if resp and resp.get("state"):
            data = resp.get("data", [])
            if data:
                paths = [item.get("file_name", "") for item in data]
                return "/" + "/".join(p for p in paths if p)
    except Exception as e:
        logger.debug("【监控生活事件】fs_info 查询父目录失败 parent_id=%s: %s", parent_id, e)
    return ""


def _sync_write_single_strm(
    p115_client, pick_code: str, file_name: str, parent_id: str,
    cloud_path: str, strm_root: Path,
    link_host: str, url_tmpl: str, video_exts: set,
) -> str:
    """精确为单个文件生成 STRM，对齐 p115strmhelper MonitorLife.creata_strm"""
    ext = Path(file_name).suffix.lstrip(".").lower()
    if ext not in video_exts:
        return "out_of_scope"

    if not pick_code or not (len(pick_code) == 17 and pick_code.isalnum()):
        logger.error("【监控生活事件】pick_code 无效: %r file=%s", pick_code, file_name)
        return "error"

    parent_dir = _sync_get_parent_path(p115_client, parent_id)
    item_path  = (parent_dir.rstrip("/") + "/" + file_name) if parent_dir else ""

    cloud_root = "/" + cloud_path.strip("/")
    if item_path:
        norm_path = "/" + item_path.strip("/")
        if not norm_path.startswith(cloud_root + "/") and norm_path != cloud_root:
            return "out_of_scope"
        try:
            rel_dir = Path(str(Path(norm_path).parent)).relative_to(cloud_root)
        except ValueError:
            rel_dir = Path(".")
    else:
        rel_dir = Path(".")

    strm_url = render_strm_url(url_tmpl, link_host, pick_code, file_name, item_path)
    logger.info("【监控生活事件】处理文件: %s → %s/%s",
                item_path or file_name, strm_root / rel_dir, file_name)
    return write_strm(strm_root, rel_dir, file_name, strm_url, overwrite_mode="overwrite")


class P115LifeMonitorService:
    """115 生活事件监控服务"""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_event_time: int = int(time.time())
        self._last_event_id:   int = 0
        self._event_log: list = []

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def get_config(self) -> dict:
        defaults = {"enabled": False, "poll_interval": 30, "auto_inc_sync": True}
        saved = await load_monitor_config()
        return {**defaults, **saved}

    async def save_config(self, config: dict) -> bool:
        await save_monitor_config(config)
        return True

    def get_status(self) -> dict:
        return {
            "running":         self.is_running,
            "last_event_time": self._last_event_time,
            "last_event_id":   self._last_event_id,
            "recent_events":   self._event_log[-20:],
        }

    async def start(self) -> dict:
        if self.is_running:
            return {"success": False, "message": "监控已在运行中"}
        self._task = asyncio.create_task(self._monitor_loop())
        return {"success": True, "message": "生活事件监控已启动"}

    async def stop(self) -> dict:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._running = False
        return {"success": True, "message": "生活事件监控已停止"}

    async def _monitor_loop(self):
        self._running = True
        logger.info("【监控生活事件】启动 from_time=%d from_id=%d",
                    self._last_event_time, self._last_event_id)
        try:
            while True:
                wait_secs = 20
                try:
                    config        = await self.get_config()
                    poll_interval = max(10, config.get("poll_interval", 30))
                    new_events    = await self._poll_once()
                    if new_events:
                        logger.info("【监控生活事件】收到 %d 条新事件", len(new_events))
                        await self._handle_events(new_events, config)
                        wait_secs = 0
                    else:
                        wait_secs = max(20, poll_interval)
                        logger.debug("【监控生活事件】无新事件，%ds 后再轮询", wait_secs)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("【监控生活事件】轮询异常: %s", e, exc_info=True)
                    wait_secs = 30
                if wait_secs > 0:
                    await asyncio.sleep(wait_secs)
        except asyncio.CancelledError:
            logger.info("【监控生活事件】监控已停止")
        finally:
            self._running = False

    async def _poll_once(self) -> list:
        manager = _get_manager()
        if not manager.enabled or not manager.ready:
            return []
        p115_client = manager.adapter._get_p115_client()
        if p115_client is None:
            return []
        login_app = getattr(manager.adapter._auth, "login_app", "web") or "web"

        events = None
        for attempt in range(3, -1, -1):
            try:
                events = await asyncio.to_thread(
                    _sync_fetch_life_events, p115_client,
                    self._last_event_time, self._last_event_id, login_app,
                )
                if events is not None:
                    break
            except Exception as e:
                if attempt <= 0:
                    logger.error("【监控生活事件】拉取失败（重试耗尽）: %s", e)
                    return []
                logger.warning("【监控生活事件】拉取失败，剩余重试%d次: %s", attempt, e)
                await asyncio.sleep(2)

        if not events:
            return []

        max_time = max(ev["time"] for ev in events)
        max_id   = max((ev.get("event_id", 0) for ev in events if ev["time"] == max_time), default=0)
        if max_time > self._last_event_time or (
            max_time == self._last_event_time and max_id > self._last_event_id
        ):
            self._last_event_time = max_time
            self._last_event_id   = max_id

        return events

    async def _handle_events(self, events: list, config: dict):
        manager = _get_manager()
        p115_client = manager.adapter._get_p115_client() if manager.ready else None

        from src.services.p115.strm_sync_service import P115StrmSyncService
        strm_svc    = P115StrmSyncService()
        strm_config = await strm_svc.get_config()
        sync_pairs  = strm_config.get("sync_pairs", [])
        video_exts  = get_video_exts(strm_config)
        link_host   = get_link_host(strm_config)
        url_tmpl    = await get_url_template()

        need_inc_sync = False
        stats = {"created": 0, "skipped": 0, "out_of_scope": 0, "errors": 0}

        for ev in events:
            ev_type   = ev["type"]
            file_name = ev["file_name"]
            parent_id = ev["parent_id"]
            pick_code = ev["pick_code"]
            self._add_event_log(ev)

            if ev_type == 22:
                logger.info("【监控生活事件】删除事件（仅记录，不删STRM）: %s", file_name)
                continue

            if ev_type in _DIR_OP_TYPES:
                logger.info("【监控生活事件】目录操作，标记兜底增量同步: %s", file_name)
                need_inc_sync = True
                continue

            handled = False
            for pair in sync_pairs:
                cloud_path    = pair.get("cloud_path", "").strip().strip("/")
                strm_root_str = pair.get("strm_path",  "").strip()
                if not cloud_path or not strm_root_str:
                    continue

                result = await asyncio.to_thread(
                    _sync_write_single_strm,
                    p115_client, pick_code, file_name, parent_id,
                    cloud_path, Path(strm_root_str),
                    link_host, url_tmpl, video_exts,
                )
                if result in ("created", "skipped", "error"):
                    stats[result if result != "skipped" else "skipped"] += 1
                    handled = True
                    break
                elif result == "out_of_scope":
                    stats["out_of_scope"] += 1

            if not handled:
                logger.info("【监控生活事件】%s 不在监控范围，标记兜底增量同步", file_name)
                need_inc_sync = True

        logger.info("【监控生活事件】处理完毕 created=%d skipped=%d out_of_scope=%d errors=%d",
                    stats["created"], stats["skipped"], stats["out_of_scope"], stats["errors"])

        if need_inc_sync and config.get("auto_inc_sync", True):
            result = await strm_svc.trigger_inc_sync()
            logger.info("【监控生活事件】触发兜底增量同步: %s", result)

    def _add_event_log(self, event: dict):
        self._event_log.append(event)
        if len(self._event_log) > 100:
            self._event_log = self._event_log[-100:]


# 全局单例
_life_monitor_service: Optional[P115LifeMonitorService] = None


def get_life_monitor_service() -> P115LifeMonitorService:
    global _life_monitor_service
    if _life_monitor_service is None:
        _life_monitor_service = P115LifeMonitorService()
    return _life_monitor_service

