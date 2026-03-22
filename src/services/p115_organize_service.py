# src/services/p115_organize_service.py
# 115 文件整理分类服务（将网盘指定目录文件移动到分类目录）
#
# 分类规则数据结构（新版，支持关键词/正则/目录名匹配）：
# categories: [
#   {
#     "name": "动漫",          # 分类名称
#     "target_dir": "动漫",    # 目标子目录（相对于 target_root）
#     "match_all": false,      # true=AND 全部规则匹配，false=OR 任一规则匹配
#     "rules": [               # 匹配规则列表（空=兜底分类）
#       {"type": "keyword", "field": "filename", "value": "动漫"},
#       {"type": "regex",   "field": "dirname",  "value": "(?i)anime"},
#     ]
#   }
# ]

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

_115_MOVE_URL = "https://webapi.115.com/files/move"
_115_MKDIR_URL = "https://webapi.115.com/files/add_folder"

# 默认分类规则配置（列表结构，支持关键词/正则/目录名匹配）
_DEFAULT_CATEGORIES = [
    {
        "name": "动漫",
        "target_dir": "动漫",
        "match_all": False,
        "rules": [
            {"type": "keyword", "field": "filename", "value": "动漫"},
            {"type": "keyword", "field": "filename", "value": "动画"},
            {"type": "keyword", "field": "filename", "value": "番剧"},
            {"type": "keyword", "field": "dirname",  "value": "动漫"},
            {"type": "keyword", "field": "dirname",  "value": "番剧"},
            {"type": "regex",   "field": "filename", "value": r"(?i)(anime|OVA|OAD)"},
        ],
    },
    {
        "name": "纪录片",
        "target_dir": "纪录片",
        "match_all": False,
        "rules": [
            {"type": "keyword", "field": "filename", "value": "纪录片"},
            {"type": "keyword", "field": "filename", "value": "纪录"},
            {"type": "keyword", "field": "dirname",  "value": "纪录片"},
            {"type": "regex",   "field": "filename", "value": r"(?i)documentary"},
        ],
    },
    {
        "name": "综艺",
        "target_dir": "综艺",
        "match_all": False,
        "rules": [
            {"type": "keyword", "field": "filename", "value": "综艺"},
            {"type": "keyword", "field": "filename", "value": "真人秀"},
            {"type": "keyword", "field": "dirname",  "value": "综艺"},
            {"type": "regex",   "field": "filename", "value": r"(?i)(variety|reality)"},
        ],
    },
    {
        "name": "剧集",
        "target_dir": "剧集",
        "match_all": False,
        "rules": [
            {"type": "regex",   "field": "filename", "value": r"(?i)(S\d+E\d+|Season\s*\d+)"},
            {"type": "regex",   "field": "filename", "value": r"(?i)(第\s*\d+\s*[集话]|EP\d+)"},
            {"type": "regex",   "field": "filename", "value": r"\d{4}\.\d{2}\.\d{2}"},
            {"type": "keyword", "field": "dirname",  "value": "剧集"},
            {"type": "keyword", "field": "dirname",  "value": "电视剧"},
        ],
    },
    {
        "name": "电影",
        "target_dir": "电影",
        "match_all": False,
        "rules": [],  # 空规则 = 默认兜底
    },
]


def _match_rule(rule: dict, filename: str, dirname: str) -> bool:
    """执行单条规则匹配"""
    field = rule.get("field", "filename")
    text = filename if field == "filename" else dirname
    value = rule.get("value", "")
    if not value:
        return False
    try:
        if rule.get("type") == "regex":
            return bool(re.search(value, text))
        else:  # keyword — 大小写不敏感包含
            return value.lower() in text.lower()
    except Exception:
        return False


def _detect_category(filename: str, dirname: str, categories: list) -> Optional[str]:
    """
    按顺序用可配置规则匹配分类，返回分类名。
    - 空规则分类作为兜底（fallback），取最后一个空规则分类
    - 无任何匹配且无兜底时返回 None
    """
    fallback = None
    for cat in categories:
        rules = cat.get("rules", [])
        cat_name = cat.get("name", "")
        if not cat_name:
            continue
        if not rules:
            fallback = cat_name
            continue
        match_all = cat.get("match_all", False)
        if match_all:
            matched = all(_match_rule(r, filename, dirname) for r in rules)
        else:
            matched = any(_match_rule(r, filename, dirname) for r in rules)
        if matched:
            return cat_name
    return fallback


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
            "source_paths": [],
            "target_root": "",
            "categories": _DEFAULT_CATEGORIES,
            "dry_run": False,
        }
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _ORGANIZE_CONFIG_KEY)
            )
            cfg = result.scalars().first()
            if cfg and cfg.value:
                try:
                    saved = json.loads(cfg.value)
                    # 向后兼容：旧格式 categories 是 dict，自动迁移为新列表结构
                    if isinstance(saved.get("categories"), dict):
                        old_cats = saved["categories"]
                        saved["categories"] = [
                            {"name": k, "target_dir": v, "match_all": False, "rules": []}
                            for k, v in old_cats.items()
                        ]
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
                cfg = SystemConfig(
                    key=_ORGANIZE_CONFIG_KEY,
                    value=value,
                    description="115 整理分类配置",
                )
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
            categories = config.get("categories", _DEFAULT_CATEGORIES)
            if isinstance(categories, dict):
                categories = [
                    {"name": k, "target_dir": v, "match_all": False, "rules": []}
                    for k, v in categories.items()
                ]

            # 预先创建分类目录，得到 cid 映射
            cat_cid_map = {}
            for cat in categories:
                cat_name = cat.get("name", "")
                sub_dir = cat.get("target_dir", cat_name)
                if not cat_name or not sub_dir:
                    continue
                cid = await self._ensure_dir(
                    manager,
                    f"{config.get('target_root', '')}/{sub_dir}",
                    parent_id=target_root_id,
                )
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
                    dirname = source_path.rstrip("/").rsplit("/", 1)[-1]
                    category = _detect_category(entry.name, dirname, categories)
                    if not category:
                        stats["skipped"] += 1
                        logger.debug("[整理] 无匹配分类，跳过: %s", entry.name)
                        continue
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
                    cfg = SystemConfig(
                        key=_ORGANIZE_STATUS_KEY,
                        value=value,
                        description="115 整理分类状态",
                    )
                    db.add(cfg)
                await db.commit()
            self._running = False
            self._progress = {"stage": "done", **stats}
            logger.info("[整理] 完成: %s 耗时 %.1fs", stats, elapsed)

    async def _ensure_dir(self, manager, path: str, parent_id: str = "") -> str:
        """确保目录存在，返回 cid（不存在则返回空串）"""
        try:
            entries = await manager.adapter.list_files(path, cid=parent_id or "0")
            target_name = path.rstrip("/").rsplit("/", 1)[-1]
            for e in entries:
                if e.is_dir and e.name == target_name:
                    return e.file_id
        except Exception:
            pass
        return ""

    async def _move_file(self, manager, file_id: str, target_cid: str) -> bool:
        """移动文件到目标目录（调用 115 API）"""
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
