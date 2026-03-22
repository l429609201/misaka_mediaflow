# src/services/p115_life_monitor_service.py
# 115 生活事件监控服务（轮询检测新增文件，触发增量STRM生成）

import asyncio
import json
import logging
import time
from typing import Optional

import httpx

from src.db import get_async_session_local
from src.db.models.system import SystemConfig
from sqlalchemy import select

logger = logging.getLogger(__name__)

_MONITOR_CONFIG_KEY = "p115_life_monitor_config"
_LIFE_URL = "https://life.115.com/api/1.0/web/1.0/life_list"


def _get_manager():
    from src.adapters.storage.p115 import P115Manager
    return P115Manager()


class P115LifeMonitorService:
    """115 生活事件监控服务"""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_event_time = int(time.time())
        self._event_log: list = []       # 最近事件日志（最多保留100条）

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def get_config(self) -> dict:
        defaults = {
            "enabled": False,
            "poll_interval": 30,           # 轮询间隔（秒）
            "monitor_paths": [],           # 监控的网盘路径（空=全部）
            "auto_inc_sync": True,         # 检测到新文件时自动触发增量同步
            "use_custom_dir": False,       # 是否使用自定义目录（否则沿用全局路径映射）
            "monitor_dir": "",             # 自定义监控目录（115网盘路径）
            "strm_dir": "",                # 自定义STRM输出目录（本地路径）
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
                cfg = SystemConfig(key=_MONITOR_CONFIG_KEY, value=value, description="115 生活事件监控配置")
                db.add(cfg)
            await db.commit()
        return True

    def get_status(self) -> dict:
        return {
            "running": self.is_running,
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
        logger.info("[生活事件] 监控已启动")

        config = await self.get_config()
        poll_interval = max(10, config.get("poll_interval", 30))
        auto_inc_sync = config.get("auto_inc_sync", True)

        # 从 strm_sync_service 懒加载
        from src.services.p115_strm_sync_service import P115StrmSyncService
        strm_svc = P115StrmSyncService()

        try:
            while True:
                try:
                    new_events = await self._poll_life_events()
                    if new_events:
                        logger.info("[生活事件] 检测到 %d 个新事件", len(new_events))
                        for ev in new_events:
                            self._add_event_log(ev)
                        if auto_inc_sync:
                            result = await strm_svc.trigger_inc_sync()
                            logger.info("[生活事件] 触发增量同步: %s", result)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("[生活事件] 轮询异常: %s", e)

                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            logger.info("[生活事件] 监控已停止")
        finally:
            self._running = False

    async def _poll_life_events(self) -> list:
        """轮询115生活事件，返回新事件列表"""
        manager = _get_manager()
        if not manager.enabled or not manager.ready:
            return []

        auth_headers = manager.adapter._auth.get_cookie_headers()
        if not auth_headers:
            return []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    _LIFE_URL,
                    params={
                        "start": 0,
                        "limit": 50,
                        "show_type": 0,   # 0 = 全部事件
                    },
                    headers=auth_headers,
                )
                data = resp.json()

            if not data.get("state"):
                return []

            items = data.get("data", {}).get("list", [])
            new_events = []
            for item in items:
                # behavior_type: 0=上传, 1=新建文件夹, 2=删除, 4=重命名, 5=移动
                ev_time = int(item.get("update_time", 0))
                if ev_time > self._last_event_time:
                    new_events.append({
                        "type": item.get("behavior_type", -1),
                        "file_name": item.get("file_name", ""),
                        "time": ev_time,
                    })

            if new_events:
                self._last_event_time = max(ev["time"] for ev in new_events)

            return new_events

        except Exception as e:
            logger.debug("[生活事件] 请求失败: %s", e)
            return []

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

