# src/services/p115_life_monitor_service.py
# 115 生活事件监控服务
#
# 参考实现：
#   - DDSRem-Dev/MoviePilot-Plugins p115strmhelper（iter_life_behavior_once + BEHAVIOR_TYPE_TO_NAME）
#   - hbq0405/emby-toolkit（p115client 直接调用 + 事件过滤）
#
# 事件类型说明（来自 p115client.tool.life.BEHAVIOR_TYPE_TO_NAME）：
#   1  = upload_image_file   上传图片      → 触发增量同步
#   2  = upload_file         上传文件/目录  → 触发增量同步
#   5  = move_image_file     移动图片      → 触发增量同步
#   6  = move_file           移动文件/目录  → 触发增量同步
#   14 = receive_files       接收文件      → 触发增量同步
#   17 = new_folder          创建新目录    → 触发增量同步
#   18 = copy_folder         复制文件夹    → 触发增量同步
#   22 = delete_file         删除文件/夹   → 触发增量同步（删除场景）
#   3  = star_image          标星图片      → 忽略
#   4  = star_file           标星文件/目录  → 忽略
#   7  = browse_image        浏览图片      → 忽略
#   8  = browse_video        浏览视频      → 忽略
#   9  = browse_audio        浏览音频      → 忽略
#   10 = browse_document     浏览文档      → 忽略
#   19 = folder_label        标签文件夹    → 忽略
#   20 = folder_rename       重命名文件夹  → 忽略

import asyncio
import json
import logging
import time
from typing import Optional

from src.db import get_async_session_local
from src.db.models.system import SystemConfig
from sqlalchemy import select

logger = logging.getLogger(__name__)

_MONITOR_CONFIG_KEY = "p115_life_monitor_config"

# 需要触发增量同步的事件类型（参考 p115strmhelper once_pull 过滤逻辑）
_SYNC_TRIGGER_TYPES = {1, 2, 5, 6, 14, 17, 18, 22}

# 事件类型中文名（对应 p115client.tool.life.BEHAVIOR_TYPE_TO_NAME）
_BEHAVIOR_TYPE_NAMES = {
    1:  "上传图片",
    2:  "上传文件/目录",
    3:  "标星图片",
    4:  "标星文件/目录",
    5:  "移动图片",
    6:  "移动文件/目录",
    7:  "浏览图片",
    8:  "浏览视频",
    9:  "浏览音频",
    10: "浏览文档",
    14: "接收文件",
    17: "创建新目录",
    18: "复制文件夹",
    19: "标签文件夹",
    20: "重命名文件夹",
    22: "删除文件/文件夹",
}


def _get_manager():
    from src.adapters.storage.p115 import P115Manager
    return P115Manager()


def _sync_fetch_life_events(p115_client, from_time: int) -> list:
    """
    同步方法：通过 p115client.tool.life.iter_life_behavior_once 拉取生活事件。
    在 asyncio.to_thread 中调用，避免阻塞事件循环。

    参考 p115strmhelper once_pull：
      - 使用 iter_life_behavior_once 拉取 from_time 之后的事件
      - 只保留 _SYNC_TRIGGER_TYPES 中的事件类型
    """
    try:
        from p115client.tool.life import iter_life_behavior_once
    except ImportError:
        # p115client 未安装或版本不含 tool.life，回退到 None
        return None  # type: ignore

    events = []
    try:
        for event in iter_life_behavior_once(
            client=p115_client,
            from_time=from_time,
            from_id=0,
            cooldown=2,
        ):
            ev_type = int(event.get("type", -1))
            # 只保留有意义的事件类型
            if ev_type not in _SYNC_TRIGGER_TYPES:
                continue
            events.append({
                "type":      ev_type,
                "type_name": _BEHAVIOR_TYPE_NAMES.get(ev_type, f"未知({ev_type})"),
                "file_name": event.get("file_name", ""),
                "file_id":   str(event.get("file_id", "")),
                "parent_id": str(event.get("parent_id", "")),
                "pick_code": event.get("pick_code", "") or event.get("pickcode", ""),
                "time":      int(event.get("update_time", 0)),
            })
    except Exception as e:
        logger.debug("[生活事件] iter_life_behavior_once 异常: %s", e)
        return None  # type: ignore

    return events


def _sync_fetch_life_events_httpx(cookie: str, ua: str, from_time: int) -> list:
    """
    同步回退方案：用 requests 直接请求 life_list 接口。
    在 iter_life_behavior_once 不可用时使用。
    参考 emby-toolkit p115_service.py 的请求方式。
    """
    import requests

    url = "https://life.115.com/api/1.0/web/1.0/life_list"
    headers = {
        "Cookie": cookie,
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        resp = requests.get(
            url,
            params={"start": 0, "limit": 100, "show_type": 0},
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            logger.debug("[生活事件] life_list 返回 HTTP %d", resp.status_code)
            return []
        if not resp.text:
            logger.debug("[生活事件] life_list 返回空响应")
            return []
        data = resp.json()
    except Exception as e:
        logger.debug("[生活事件] life_list 请求异常: %s", e)
        return []

    if not data.get("state"):
        logger.debug("[生活事件] life_list state=false: %s", data.get("error", ""))
        return []

    items = data.get("data", {}).get("list", [])
    events = []
    for item in items:
        ev_time = int(item.get("update_time", 0))
        if ev_time <= from_time:
            continue
        ev_type = int(item.get("behavior_type", -1))
        if ev_type not in _SYNC_TRIGGER_TYPES:
            continue
        events.append({
            "type":      ev_type,
            "type_name": _BEHAVIOR_TYPE_NAMES.get(ev_type, f"未知({ev_type})"),
            "file_name": item.get("file_name", ""),
            "file_id":   str(item.get("file_id", "")),
            "parent_id": str(item.get("parent_id", "")),
            "pick_code": item.get("pick_code", "") or item.get("pickcode", ""),
            "time":      ev_time,
        })
    return events


class P115LifeMonitorService:
    """115 生活事件监控服务"""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # 启动时以当前时间戳为基准，只处理此后产生的新事件
        self._last_event_time: int = int(time.time())
        self._last_event_id: int = 0
        self._event_log: list = []   # 最近事件日志（最多保留100条）

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def get_config(self) -> dict:
        defaults = {
            "enabled":       False,
            "poll_interval": 30,    # 轮询间隔（秒）
            "monitor_paths": [],    # 监控的网盘路径（空=全部）
            "auto_inc_sync": True,  # 检测到新文件时自动触发增量同步
            "use_custom_dir": False,
            "monitor_dir":   "",
            "strm_dir":      "",
        }
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _MONITOR_CONFIG_KEY)
            )
            cfg = result.scalars().first()
            if cfg and cfg.value:
                try:
                    return {**defaults, **json.loads(cfg.value)}
                except Exception:
                    pass
        return defaults

    async def save_config(self, config: dict) -> bool:
        from src.core.timezone import tm
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _MONITOR_CONFIG_KEY)
            )
            cfg = result.scalars().first()
            value = json.dumps(config, ensure_ascii=False)
            if cfg:
                cfg.value = value
                cfg.updated_at = tm.now()
            else:
                cfg = SystemConfig(
                    key=_MONITOR_CONFIG_KEY,
                    value=value,
                    description="115 生活事件监控配置",
                )
                db.add(cfg)
            await db.commit()
        return True

    def get_status(self) -> dict:
        return {
            "running":       self.is_running,
            "last_event_time": self._last_event_time,
            "recent_events": self._event_log[-20:],
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
        """主监控循环"""
        self._running = True
        logger.info("[生活事件] 监控已启动，基准时间戳 %d", self._last_event_time)

        from src.services.p115_strm_sync_service import P115StrmSyncService
        strm_svc = P115StrmSyncService()

        try:
            while True:
                try:
                    # 每轮重新读配置，保证改完配置保存后立即生效
                    config = await self.get_config()
                    poll_interval = max(10, config.get("poll_interval", 30))
                    auto_inc_sync = config.get("auto_inc_sync", True)

                    new_events = await self._poll_life_events()
                    if new_events:
                        for ev in new_events:
                            logger.info(
                                "[生活事件] 新事件 ▶ [%s] %s",
                                ev["type_name"], ev["file_name"],
                            )
                            self._add_event_log(ev)
                        if auto_inc_sync:
                            result = await strm_svc.trigger_inc_sync()
                            logger.info("[生活事件] 触发增量同步: %s", result)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("[生活事件] 轮询异常: %s", e, exc_info=True)
                    poll_interval = 30

                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            logger.info("[生活事件] 监控已停止")
        finally:
            self._running = False

    async def _poll_life_events(self) -> list:
        """
        轮询115生活事件，返回本轮新事件列表（仅包含触发增量同步的类型）。

        优先使用 p115client.tool.life.iter_life_behavior_once（参考 p115strmhelper）。
        若 p115client 版本不含 tool.life，回退到直接请求 life_list 接口。
        """
        manager = _get_manager()
        if not manager.enabled or not manager.ready:
            return []

        p115_client = manager.adapter._get_p115_client()

        if p115_client is not None:
            # ── 方案A：p115client.tool.life（推荐，自动处理 cookie/请求头/重定向）──
            events = await asyncio.to_thread(
                _sync_fetch_life_events,
                p115_client,
                self._last_event_time,
            )
        else:
            events = None

        if events is None:
            # ── 方案B：直接 HTTP（回退，加完整请求头）────────────────────────────
            auth = manager.adapter._auth
            if not auth.has_cookie:
                return []
            events = await asyncio.to_thread(
                _sync_fetch_life_events_httpx,
                auth.cookie,
                auth.get_cookie_headers().get("User-Agent", ""),
                self._last_event_time,
            )

        if not events:
            return []

        # 更新基准时间戳
        self._last_event_time = max(ev["time"] for ev in events)
        return events

    def _add_event_log(self, event: dict):
        """添加事件到日志（最多保留100条）"""
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

