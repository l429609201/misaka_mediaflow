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


def _match_rule(rule: dict, filename: str, dirname: str, tmdb: dict = None) -> bool:
    """执行单条规则匹配。支持 genre_ids / origin_country / original_language / keyword / regex。"""
    rtype = rule.get("type", "keyword")
    value = rule.get("value", "").strip()
    if not value:
        return False

    if tmdb is None:
        tmdb = {}

    # ── TMDB 字段匹配 ──────────────────────────────────────────────────
    if rtype == "genre_ids":
        want_ids = {int(v.strip()) for v in value.split(",") if v.strip().isdigit()}
        have_ids = {int(g) for g in tmdb.get("genre_ids", []) if str(g).isdigit()}
        return bool(want_ids & have_ids)

    if rtype == "origin_country":
        want = {v.strip().upper() for v in value.split(",")}
        have = {c.upper() for c in tmdb.get("origin_country", [])}
        return bool(want & have)

    if rtype == "original_language":
        want = {v.strip().lower() for v in value.split(",")}
        lang = tmdb.get("original_language", "").lower()
        return lang in want

    # ── 本地文件名匹配 ─────────────────────────────────────────────────
    field = rule.get("field", "filename")
    text = filename if field == "filename" else dirname
    try:
        if rtype == "regex":
            return bool(re.search(value, text))
        else:
            return value.lower() in text.lower()
    except Exception:
        return False


def _detect_category(
    filename: str, dirname: str, tmdb_info: dict, categories: list
) -> Optional[str]:
    """按顺序匹配分类规则，返回第一个命中的分类名；空规则分类为兜底。"""
    fallback = None
    for cat in categories:
        rules    = cat.get("rules", [])
        cat_name = cat.get("name", "")
        if not cat_name:
            continue
        if not rules:
            fallback = cat_name
            continue
        match_all = cat.get("match_all", False)
        if match_all:
            matched = all(_match_rule(r, filename, dirname, tmdb_info) for r in rules)
        else:
            matched = any(_match_rule(r, filename, dirname, tmdb_info) for r in rules)
        if matched:
            return cat_name
    return fallback


# ── TMDB 辅助（带内存缓存）─────────────────────────────────────────────────
_tmdb_cache: dict = {}


async def _get_tmdb_provider():
    """从 SystemConfig 读取 TMDB 配置，返回 TMDBProvider；未配置 API Key 则返回 None。"""
    try:
        async with get_async_session_local() as db:
            row = await db.execute(
                select(SystemConfig).where(SystemConfig.key == "metadata_tmdb")
            )
            cfg = row.scalars().first()
            if not cfg or not cfg.value:
                return None
            data    = json.loads(cfg.value)
            api_key = data.get("api_key", "").strip()
            if not api_key:
                return None
            from src.adapters.metadata.tmdb import TMDBProvider
            return TMDBProvider(api_key=api_key, language=data.get("language", "zh-CN"))
    except Exception as e:
        logger.debug("[整理] 获取 TMDB 配置失败: %s", e)
        return None


async def _fetch_tmdb_info(title: str, is_movie: bool, year: Optional[str]) -> dict:
    """搜索 TMDB，返回 {genre_ids, origin_country, original_language}；带缓存。"""
    cache_key = f"{title}|{'movie' if is_movie else 'tv'}"
    if cache_key in _tmdb_cache:
        return _tmdb_cache[cache_key]

    result: dict = {}
    tmdb = await _get_tmdb_provider()
    if tmdb is None:
        return result

    try:
        media_type = "movie" if is_movie else "tv"
        year_int   = int(year) if year and str(year).isdigit() else 0
        results    = await tmdb.search(title, media_type=media_type, year=year_int)
        if not results and year_int:
            results = await tmdb.search(title, media_type=media_type)
        if results:
            top      = results[0]
            tmdb_id  = top.extra.get("id") or top.tmdb_id
            if tmdb_id:
                detail = await tmdb.get_detail(int(tmdb_id), media_type=media_type)
                if detail:
                    result = {
                        "genre_ids":         top.extra.get("genre_ids", []),
                        "origin_country":    detail.extra.get("origin_country", []),
                        "original_language": detail.extra.get("original_language", ""),
                    }
    except Exception as e:
        logger.warning("[整理] TMDB 查询失败 title=%s: %s", title, e)

    _tmdb_cache[cache_key] = result
    return result


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
        """执行整理分类
        流程：
          ① 从 path_mapping 读取 organize_source（待整理目录）
          ② filename_parser 本地解析（title/is_movie/season/episode）
          ③ TMDB 查询（genre_ids/origin_country/original_language），需配置 API Key
          ④ 分类规则匹配（genre_ids/origin_country/keyword/regex）
          ⑤ 匹配成功 → 移入分类目录；未识别 → 移入 organize_unrecognized
        """
        self._running = True
        start_time = time.time()
        stats = {"moved": 0, "skipped": 0, "errors": 0, "unrecognized": 0}
        self._progress = {"stage": "scanning", **stats}

        try:
            config = await self.get_config()
            manager = _get_manager()
            if not manager.enabled or not manager.ready:
                logger.warning("[整理] 115 未启用或未就绪")
                return

            # ── 从 path_mapping 读待整理目录 / 未识别目录 ──────────────────
            path_mapping = await self._load_path_mapping()
            organize_source = path_mapping.get("organize_source", "").strip()
            organize_unrecognized = path_mapping.get("organize_unrecognized", "").strip()

            # source_paths 优先使用 path_mapping.organize_source，
            # 若未配置则回退到 config 里的 source_paths（向后兼容）
            if organize_source:
                source_paths = [organize_source]
            else:
                source_paths = [p.strip() for p in config.get("source_paths", []) if p.strip()]

            if not source_paths:
                logger.warning("[整理] 未配置待整理目录，退出")
                return

            # ── 目标根目录 ─────────────────────────────────────────────────
            target_root = config.get("target_root", "").strip()
            target_root_id = await self._ensure_dir(manager, target_root) if target_root else ""
            if target_root and not target_root_id:
                logger.error("[整理] 目标根目录无效: %s", target_root)
                return

            # ── 未识别目录 cid ─────────────────────────────────────────────
            unrecognized_cid = ""
            if organize_unrecognized:
                unrecognized_cid = await self._ensure_dir(manager, organize_unrecognized)
                if not unrecognized_cid:
                    logger.warning("[整理] 未识别目录无效或不存在: %s", organize_unrecognized)

            dry_run = config.get("dry_run", False)
            categories = config.get("categories", _DEFAULT_CATEGORIES)
            if isinstance(categories, dict):
                categories = [
                    {"name": k, "target_dir": v, "match_all": False, "rules": []}
                    for k, v in categories.items()
                ]

            # ── 预建分类目录 cid 映射 ────────────────────────────────────────
            cat_cid_map: dict[str, str] = {}
            if target_root_id:
                for cat in categories:
                    cat_name = cat.get("name", "")
                    sub_dir  = cat.get("target_dir", cat_name)
                    if not cat_name or not sub_dir:
                        continue
                    cid = await self._ensure_dir(
                        manager, f"{target_root}/{sub_dir}", parent_id=target_root_id,
                    )
                    if cid:
                        cat_cid_map[cat_name] = cid

            # ── TMDB 可用性 ─────────────────────────────────────────────────
            tmdb_available = (await _get_tmdb_provider()) is not None
            logger.info("[整理] TMDB %s", "已配置，启用精确分类" if tmdb_available else "未配置，使用本地规则")

            # ── 扫描待整理目录 ──────────────────────────────────────────────
            for source_path in source_paths:
                logger.info("[整理] 扫描: %s", source_path)
                try:
                    entries = await manager.adapter.list_files(source_path, cid="0")
                except Exception as e:
                    logger.error("[整理] 扫描目录失败 %s: %s", source_path, e)
                    continue

                dirname = source_path.rstrip("/").rsplit("/", 1)[-1]

                for entry in entries:
                    if entry.is_dir:
                        continue

                    filename = entry.name
                    tmdb_info: dict = {}
                    is_movie: Optional[bool] = None
                    title   = filename
                    year    = None

                    # ① 本地解析
                    try:
                        from src.utils.filename_parser import parse_filename
                        parsed  = parse_filename(filename)
                        title   = parsed.title or filename
                        year    = parsed.year
                        if parsed.season is not None or parsed.episode is not None:
                            is_movie = False
                        elif parsed.is_movie:
                            is_movie = True
                    except Exception as ex:
                        logger.debug("[整理] filename_parser 失败: %s", ex)

                    # ② TMDB 查询
                    if tmdb_available:
                        if is_movie is None:
                            tmdb_info = await _fetch_tmdb_info(title, True, year)
                            if not tmdb_info:
                                tmdb_info = await _fetch_tmdb_info(title, False, year)
                        else:
                            tmdb_info = await _fetch_tmdb_info(title, is_movie, year)

                    # ③ 分类匹配
                    category = _detect_category(filename, dirname, tmdb_info, categories)

                    if not category or not cat_cid_map.get(category):
                        # 未识别 → 移入未识别目录
                        if unrecognized_cid:
                            if dry_run:
                                logger.info("[整理][试运行] 未识别 %s → 未识别目录", filename)
                            else:
                                ok = await self._move_file(manager, entry.file_id, unrecognized_cid)
                                if ok:
                                    stats["unrecognized"] += 1
                                    logger.info("[整理] 未识别: %s → 未识别目录", filename)
                                else:
                                    stats["errors"] += 1
                        else:
                            stats["skipped"] += 1
                            logger.debug("[整理] 无匹配分类，跳过: %s", filename)
                        continue

                    target_cid = cat_cid_map[category]
                    if dry_run:
                        logger.info("[整理][试运行] %s → %s (tmdb=%s)", filename, category, bool(tmdb_info))
                        stats["moved"] += 1
                        continue

                    ok = await self._move_file(manager, entry.file_id, target_cid)
                    if ok:
                        stats["moved"] += 1
                        logger.info("[整理] %s → %s", filename, category)
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
                row = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == _ORGANIZE_STATUS_KEY)
                )
                cfg = row.scalars().first()
                value = json.dumps(status_val, ensure_ascii=False)
                if cfg:
                    cfg.value = value; cfg.updated_at = tm.now()
                else:
                    cfg = SystemConfig(
                        key=_ORGANIZE_STATUS_KEY, value=value,
                        description="115 整理分类状态",
                    )
                    db.add(cfg)
                await db.commit()
            self._running = False
            self._progress = {"stage": "done", **stats}
            logger.info("[整理] 完成: %s 耗时 %.1fs", stats, elapsed)

    async def _load_path_mapping(self) -> dict:
        """从 SystemConfig 读取 path_mapping（organize_source / organize_unrecognized）"""
        try:
            async with get_async_session_local() as db:
                row = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == "p115_path_mapping")
                )
                cfg = row.scalars().first()
                if cfg and cfg.value:
                    return json.loads(cfg.value)
        except Exception as e:
            logger.warning("[整理] 读取 path_mapping 失败: %s", e)
        return {}

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
