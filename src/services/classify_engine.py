# src/services/classify_engine.py
# 通用分类引擎（纯逻辑层）
#
# 职责：
#   1. 分类规则配置的读写（存入 SystemConfig）
#   2. detect_category() → 对单个文件执行规则匹配，返回分类名
#
# 元数据查询统一通过 metadata_service 调用，不直接接触任何具体 Provider。
# 调用方式（任意任务模块皆可直接 import）：
#   from src.services.classify_engine import detect_category, get_config, save_config
#   from src.services.classify_engine import fetch_meta_info, is_meta_available
#
# 分类规则数据结构：
# {
#   "enabled": true,
#   "categories": [
#     {
#       "name": "动漫",
#       "target_dir": "动漫",
#       "match_all": false,
#       "rules": [
#         {"type": "keyword", "field": "filename", "value": "动漫"},
#         {"type": "regex",   "field": "dirname",  "value": "(?i)anime"},
#         {"type": "genre_ids",         "value": "16"},
#         {"type": "origin_country",    "value": "JP"},
#         {"type": "original_language", "value": "ja"}
#       ]
#     }
#   ]
# }

import json
import logging
import re
from typing import Optional

from sqlalchemy import select

from src.db import get_async_session_local
from src.db.models.system import SystemConfig

logger = logging.getLogger(__name__)

_CONFIG_KEY = "classify_engine_config"

# ─── 默认分类规则 ─────────────────────────────────────────────────────────────

DEFAULT_CATEGORIES = [
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
            {"type": "genre_ids",         "value": "16"},
            {"type": "origin_country",    "value": "JP"},
        ],
    },
    {
        "name": "纪录片",
        "target_dir": "纪录片",
        "match_all": False,
        "rules": [
            {"type": "keyword", "field": "filename", "value": "纪录片"},
            {"type": "keyword", "field": "dirname",  "value": "纪录片"},
            {"type": "regex",   "field": "filename", "value": r"(?i)documentary"},
            {"type": "genre_ids", "value": "99"},
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
            {"type": "keyword", "field": "dirname",  "value": "剧集"},
            {"type": "keyword", "field": "dirname",  "value": "电视剧"},
        ],
    },
    {
        "name": "电影",
        "target_dir": "电影",
        "match_all": False,
        "rules": [],   # 空规则 = 默认兜底
    },
]

_DEFAULT_CONFIG = {
    "enabled": True,
    "categories": DEFAULT_CATEGORIES,
}


# ─── 配置读写 ─────────────────────────────────────────────────────────────────

async def get_config() -> dict:
    """读取分类引擎配置，不存在则返回默认值。"""
    async with get_async_session_local() as db:
        row = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _CONFIG_KEY)
        )
        cfg = row.scalars().first()
        if cfg and cfg.value:
            try:
                saved = json.loads(cfg.value)
                # 向后兼容：旧 p115_organize_config 的 dict 格式自动迁移
                if isinstance(saved.get("categories"), dict):
                    saved["categories"] = [
                        {"name": k, "target_dir": v, "match_all": False, "rules": []}
                        for k, v in saved["categories"].items()
                    ]
                return {**_DEFAULT_CONFIG, **saved}
            except Exception:
                pass
    return dict(_DEFAULT_CONFIG)


async def save_config(config: dict) -> bool:
    """保存分类引擎配置。"""
    from src.core.timezone import tm
    async with get_async_session_local() as db:
        row = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _CONFIG_KEY)
        )
        cfg = row.scalars().first()
        value = json.dumps(config, ensure_ascii=False)
        if cfg:
            cfg.value = value
            cfg.updated_at = tm.now()
        else:
            cfg = SystemConfig(
                key=_CONFIG_KEY,
                value=value,
                description="通用整理分类引擎配置",
            )
            db.add(cfg)
        await db.commit()
    logger.info("[分类引擎] 配置已保存，共 %d 个分类", len(config.get("categories", [])))
    return True


# ─── 规则匹配核心 ─────────────────────────────────────────────────────────────

def _match_rule(rule: dict, filename: str, dirname: str, tmdb: dict) -> bool:
    """执行单条规则匹配。"""
    rtype = rule.get("type", "keyword")
    value = rule.get("value", "").strip()
    if not value:
        return False

    # TMDB 字段匹配
    if rtype == "genre_ids":
        want = {int(v.strip()) for v in value.split(",") if v.strip().isdigit()}
        have = {int(g) for g in tmdb.get("genre_ids", []) if str(g).isdigit()}
        return bool(want & have)

    if rtype == "origin_country":
        want = {v.strip().upper() for v in value.split(",")}
        have = {c.upper() for c in tmdb.get("origin_country", [])}
        return bool(want & have)

    if rtype == "original_language":
        want = {v.strip().lower() for v in value.split(",")}
        return tmdb.get("original_language", "").lower() in want

    # 本地文件名匹配
    field = rule.get("field", "filename")
    text = filename if field == "filename" else dirname
    try:
        if rtype == "regex":
            return bool(re.search(value, text))
        return value.lower() in text.lower()   # keyword
    except Exception:
        return False


def detect_category(
    filename: str,
    dirname: str,
    tmdb_info: dict,
    categories: list,
) -> Optional[str]:
    """
    对单个文件执行分类规则匹配。

    Args:
        filename:   文件名（含扩展名）
        dirname:    所在目录名
        tmdb_info:  TMDB 元数据 dict（可为空 {}）
        categories: 分类规则列表（来自 get_config()["categories"]）

    Returns:
        命中的分类名；如果有兜底分类则返回兜底名；否则返回 None。
    """
    fallback: Optional[str] = None
    for cat in categories:
        name  = cat.get("name", "")
        rules = cat.get("rules", [])
        if not name:
            continue
        if not rules:
            fallback = name   # 无规则 → 兜底
            continue
        match_all = cat.get("match_all", False)
        if match_all:
            matched = all(_match_rule(r, filename, dirname, tmdb_info) for r in rules)
        else:
            matched = any(_match_rule(r, filename, dirname, tmdb_info) for r in rules)
        if matched:
            return name
    return fallback


# ─── 元数据查询（委托给 metadata_service）────────────────────────────────────
# classify_engine 不直接接触任何具体 Provider（TMDB / 豆瓣 / Bangumi 等）
# 全部通过 metadata_service 的统一接口调用，以实现真正的模块化。

async def fetch_meta_info(
    title: str,
    is_movie: bool,
    year: Optional[str] = None,
    provider_name: str = "tmdb",
) -> dict:
    """
    查询元数据，返回可用于规则匹配的字段。
    委托给 metadata_service.fetch_classify_info()，带缓存。

    返回格式：
        {"genre_ids": [...], "origin_country": [...], "original_language": "ja"}
    Provider 未配置或查询失败时返回 {}。
    """
    from src.services.metadata_service import metadata_service
    return await metadata_service.fetch_classify_info(
        title=title,
        is_movie=is_movie,
        year=year,
        provider_name=provider_name,
    )


async def is_meta_available(provider_name: str = "tmdb") -> bool:
    """检查指定元数据 Provider 是否已配置可用。"""
    from src.services.metadata_service import metadata_service
    return await metadata_service.is_provider_available(provider_name)


# ── 向后兼容别名（旧代码调用 fetch_tmdb_info / is_tmdb_available 不报错）──────
async def fetch_tmdb_info(title: str, is_movie: bool, year: Optional[str] = None) -> dict:
    return await fetch_meta_info(title, is_movie, year, provider_name="tmdb")


async def is_tmdb_available() -> bool:
    return await is_meta_available("tmdb")


