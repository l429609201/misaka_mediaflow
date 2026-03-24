# src/services/p115/modules/config_helper.py
# 配置辅助模块
# 负责从同步配置中提取 link_host、video_exts、sync_pairs 等运行时参数。

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 默认视频扩展名（对齐 p115strmhelper）
DEFAULT_VIDEO_EXTS = frozenset({
    "mp4", "mkv", "avi", "ts", "iso", "mov", "m2ts",
    "rmvb", "flv", "wmv", "m4v",
})


def get_video_exts(config: dict) -> set:
    """从配置解析视频扩展名集合"""
    raw = config.get("file_extensions", "")
    if raw:
        return {e.strip().lower() for e in raw.split(",") if e.strip()}
    return set(DEFAULT_VIDEO_EXTS)


def get_link_host(config: dict) -> str:
    """
    获取 STRM 链接的 base URL。
    优先使用配置中 strm_link_host，支持路径形式（/ctl/115open）和 http 形式。
    fallback 顺序：strm_link_host → external_url → http://127.0.0.1:{port}
    """
    from src.core.config import settings

    host = (config.get("strm_link_host") or "").strip()
    if host:
        return host.rstrip("/")

    try:
        external = (settings.server.external_url or "").strip().rstrip("/")
        if external:
            return external
    except Exception:
        pass

    try:
        port = settings.server.port or 7789
    except Exception:
        port = 7789

    return f"http://127.0.0.1:{port}"


def resolve_sync_pairs(config: dict, mode: str) -> list[dict]:
    """
    解析同步路径对列表。
    mode: "full" 或 "inc"
    优先使用对应模式的自定义路径（use_custom=True），fallback 到全局 sync_pairs。
    """
    key = "full_sync_cfg" if mode == "full" else "inc_sync_cfg"
    custom_cfg = config.get(key, {})
    if custom_cfg.get("use_custom") and custom_cfg.get("cloud_path") and custom_cfg.get("strm_path"):
        return [{
            "cloud_path": custom_cfg["cloud_path"].strip(),
            "strm_path":  custom_cfg["strm_path"].strip(),
        }]
    return [
        p for p in config.get("sync_pairs", [])
        if p.get("cloud_path", "").strip() and p.get("strm_path", "").strip()
    ]

