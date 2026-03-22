# src/services/p115_organize_service.py
# 115 文件整理分类服务（将网盘指定目录文件移动到分类目录）

import asyncio
import json
import logging
import re
import time
from typing import Optional

from src.db import get_async_session_local
from src.db.models.system import SystemConfig
from sqlalchemy import select

logger = logging.getLogger(__name__)

_ORGANIZE_CONFIG_KEY = "p115_organize_config"
_ORGANIZE_STATUS_KEY = "p115_organize_status"

# 115 文件管理 API
_115_MOVE_URL = "https://webapi.115.com/files/move"
_115_MKDIR_URL = "https://webapi.115.com/files/add_folder"

# 主分类关键词识别规则（正则匹配文件名）
_CATEGORY_RULES = [
    {
        "name": "动漫",
        "patterns": [
            r"(?i)(anime|动漫|动画|番剧|OVA|OAD|剧场版(?!.*电影))",
            r"(?i)\[(动漫|动画|Anime)\]",
        ]
    },
    {
        "name": "纪录片",
        "patterns": [
            r"(?i)(documentary|纪录片|纪录|记录片|自然|探索)",
        ]
    },
    {
        "name": "综艺",
        "patterns": [
            r"(?i)(variety|综艺|真人秀|reality|show)",
        ]
    },
    {
        "name": "剧集",
        "patterns": [
            r"(?i)(S\d+E\d+|Season\s*\d+|第\s*\d+\s*集|第\s*\d+\s*话|EP\d+|E\d+)",
            r"(?i)\d{4}\.\d{2}\.\d{2}",  # 日播节目格式
        ]
    },
    # 默认 → 电影
]


def _detect_category(filename: str) -> str:
    """根据文件名检测分类"""
    for rule in _CATEGORY_RULES:
        for pattern in rule["patterns"]:
            if re.search(pattern, filename):
                return rule["name"]
    return "电影"


def _get_manager():
    from src.adapters.storage.p115 import P115Manager
    return P115Manager()


class P115OrganizeService:
    """115 文件整理分类服务"""

    def __init__(self):
        self._running = False
        self._progress = {}

    async def get_config(self) -> dict:
        defaults = {
            "source_paths": [],        # 待整理的源目录（网盘路径）
            "target_root": "",         # 目标根目录（分类后存放的根目录）
            "categories": {            # 分类配置（分类名 → 子目录）
                "电影": "电影",
                "剧集": "剧集",
                "动漫": "动漫",
                "纪录片": "纪录片",
                "综艺": "综艺",
            },
            "enable_region": False,    # 是否启用地区二级分类
            "dry_run": False,          # 试运行（不实际移动）
        }
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _ORGANIZE_CONFIG_KEY)
            )
            cfg = result.scalars().first()
            if cfg and cfg.value:
                try:
                    saved = json.loads(cfg.value)
                    return {**defaults, **saved}
                except Exception:
                    pass
        return defaults

    async def save_config(self, config: dict) -> bool:
        from src.core.timezone import tm
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _ORGANIZE_CONFIG_KEY)
            )
            cfg = result.scalars().first()
            value = json.dumps(config, ensure_ascii=False)
            if cfg:
                cfg.value = value
                cfg.updated_at = tm.now()
            else:
                cfg = SystemConfig(key=_ORGANIZE_CONFIG_KEY, value=value, description="115 整理分类配置")
                db.add(cfg)
            await db.commit()
        return True

    async def get_status(self) -> dict:
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _ORGANIZE_STATUS_KEY)
            )
            cfg = result.scalars().first()
            status = {}
            if cfg and cfg.value:
                try:
                    status = json.loads(cfg.value)
                except Exception:
                    pass
        status["running"] = self._running
        status["progress"] = self._progress
        return status

    async def trigger_organize(self) -> dict:
        """触发整理分类任务"""
        if self._running:
            return {"success": False, "message": "整理任务正在进行中"}
        asyncio.create_task(self._do_organize())
        return {"success": True, "message": "整理任务已启动"}

    async def _do_organize(self):
        """执行整理分类"""
        self._running = True
        start_time = time.time()
        stats = {"moved": 0, "skipped": 0, "errors": 0}
        self._progress = {"stage": "scanning", **stats}

        try:
            config = await self.get_config()
            manager = _get_manager()
            if not manager.enabled or not manager.ready:
                logger.warning("[整理] 115 未启用或未就绪")
                return

            target_root_id = await self._ensure_dir(manager, config.get("target_root", ""))
            if not target_root_id:
                logger.error("[整理] 目标根目录无效: %s", config.get("target_root"))
                return

            dry_run = config.get("dry_run", False)
            categories = config.get("categories", {})
            # 预先创建分类目录，得到 cid 映射
            cat_cid_map = {}
            for cat_name, sub_dir in categories.items():
                cid = await self._ensure_dir(manager, f"{config.get('target_root', '')}/{sub_dir}", parent_id=target_root_id)
                if cid:
                    cat_cid_map[cat_name] = cid

            for source_path in config.get("source_paths", []):
                source_path = source_path.strip()
                if not source_path:
                    continue
                logger.info("[整理] 扫描源目录: %s", source_path)
                entries = await manager.adapter.list_files(source_path, cid="0")
                for entry in entries:
                    if entry.is_dir:
                        continue
                    category = _detect_category(entry.name)
                    target_cid = cat_cid_map.get(category)
                    if not target_cid:
                        stats["skipped"] += 1
                        continue
                    if dry_run:
                        logger.info("[整理][试运行] %s → %s", entry.name, category)
                        stats["moved"] += 1
                        continue
                    ok = await self._move_file(manager, entry.file_id, target_cid)
                    if ok:
                        stats["moved"] += 1
                        logger.info("[整理] 移动: %s → %s", entry.name, category)
                    else:
                        stats["errors"] += 1
                self._progress = {"stage": "organizing", **stats}

        except Exception as e:
            logger.error("[整理] 异常: %s", e, exc_info=True)
            stats["errors"] += 1
        finally:
            elapsed = round(time.time() - start_time, 1)
            from src.core.timezone import tm
            status_val = {
                "last_organize": int(time.time()),
                "last_organize_stats": stats,
                "last_organize_elapsed": elapsed,
            }
            async with get_async_session_local() as db:
                result = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == _ORGANIZE_STATUS_KEY)
                )
                cfg = result.scalars().first()
                value = json.dumps(status_val, ensure_ascii=False)
                if cfg:
                    cfg.value = value
                    cfg.updated_at = tm.now()
                else:
                    cfg = SystemConfig(key=_ORGANIZE_STATUS_KEY, value=value, description="115 整理分类状态")
                    db.add(cfg)
                await db.commit()
            self._running = False
            self._progress = {"stage": "done", **stats}
            logger.info("[整理] 完成: %s 耗时 %.1fs", stats, elapsed)

    async def _ensure_dir(self, manager, path: str, parent_id: str = "") -> str:
        """确保目录存在，返回 cid（不存在则尝试创建）"""
        # 通过 list_files 查找目录（简单实现：遍历父目录找同名子目录）
        try:
            entries = await manager.adapter.list_files(path, cid=parent_id or "0")
            for e in entries:
                if e.is_dir and e.name == path.rstrip("/").rsplit("/", 1)[-1]:
                    return e.file_id
        except Exception:
            pass
        return ""

    async def _move_file(self, manager, file_id: str, target_cid: str) -> bool:
        """移动文件到目标目录（调用115 API）"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    _115_MOVE_URL,
                    data={"fid[0]": file_id, "pid": target_cid},
                    headers=manager.adapter._auth.get_cookie_headers(),
                )
                data = resp.json()
                return bool(data.get("state"))
        except Exception as e:
            logger.error("[整理] 移动文件失败 fid=%s: %s", file_id, e)
            return False

