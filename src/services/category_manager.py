# src/services/category_manager.py
# 分类管理器 — 决定 STRM 文件的存放路径
#
# 设计原则:
#   纯逻辑层，不碰数据库。配置由 service 层注入（和 http_proxy 同模式）。
#
# 路径模板变量:
#   {type}           → 类型标签（电影/电视剧/动漫）
#   {title}          → 标题
#   {series_title}   → 剧集名（Episode 的父级剧名）
#   {year}           → 年份
#   {season}         → 季号
#   {episode}        → 集号
#   {ext}            → 文件扩展名（不含点）
#   {quality}        → 画质标签（4K/1080P/720P）
#   {video_codec}    → 视频编码
#   {tmdb_id}        → TMDB ID

import logging
import re
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

# ── 模块级配置（由外部注入）──

_config: dict = {
    "enabled": True,
    "movie_template": "{type}/{title} ({year})/{title} ({year}).strm",
    "episode_template": "{type}/{series_title}/Season {season:02d}/{series_title} - S{season:02d}E{episode:02d}.strm",
    "type_labels": {
        "Movie": "电影",
        "Episode": "电视剧",
    },
}

# 非法文件名字符
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def configure(cfg: dict) -> None:
    """注入 / 刷新分类配置"""
    global _config
    _config = {
        "enabled": cfg.get("enabled", True),
        "movie_template": cfg.get("movie_template") or _config["movie_template"],
        "episode_template": cfg.get("episode_template") or _config["episode_template"],
        "type_labels": cfg.get("type_labels") or _config["type_labels"],
    }
    logger.info("[category] 配置已注入: enabled=%s", _config["enabled"])


def get_config() -> dict:
    return {**_config}


# ── 工具函数 ──

def _sanitize(name: str) -> str:
    """清理文件名非法字符"""
    if not name:
        return "Unknown"
    name = _ILLEGAL.sub("", name).strip(". ")
    return name or "Unknown"


def _guess_quality(path: str) -> str:
    p = path.lower() if path else ""
    if "2160p" in p or "4k" in p or "uhd" in p:
        return "4K"
    if "1080p" in p or "1080i" in p:
        return "1080P"
    if "720p" in p:
        return "720P"
    return ""


def _is_anime(item, tmdb_genres: list | None = None) -> bool:
    """检测是否为动漫"""
    if tmdb_genres:
        names = {g if isinstance(g, str) else g.get("name", "") for g in tmdb_genres}
        if names & {"Animation", "动画", "动漫", "アニメ"}:
            return True
    path = getattr(item, "file_path", "") or ""
    return any(kw in path for kw in ("动漫", "动画", "anime", "Anime"))


# ── 核心：路径解析 ──

def resolve_path(
    item,
    *,
    output_dir: str = "",
    series_title: str = "",
    tmdb_genres: list | None = None,
) -> str:
    """
    根据 MediaItem 元数据生成分类路径。

    Args:
        item: 需要 item_type, title, year, season_num, episode_num, file_path 等属性
        output_dir: 输出根目录
        series_title: 剧集父级剧名
        tmdb_genres: TMDB genres 列表（用于动漫检测）

    Returns:
        完整 STRM 文件路径
    """
    if not _config["enabled"]:
        return _fallback(item, output_dir)

    item_type = getattr(item, "item_type", "Movie") or "Movie"
    title = _sanitize(getattr(item, "title", "") or "Unknown")
    year = getattr(item, "year", 0) or 0
    season = getattr(item, "season_num", 0) or 0
    episode = getattr(item, "episode_num", 0) or 0
    file_path = getattr(item, "file_path", "") or ""
    video_codec = getattr(item, "video_codec", "") or ""
    tmdb_id = getattr(item, "tmdb_id", 0) or 0

    ext = PurePosixPath(file_path).suffix.lstrip(".") if file_path else "mkv"
    quality = _guess_quality(file_path)
    s_title = _sanitize(series_title) if series_title else title

    # 类型标签
    if _is_anime(item, tmdb_genres):
        type_label = "动漫"
    else:
        type_label = _config["type_labels"].get(item_type, item_type)

    template = _config["episode_template"] if item_type == "Episode" else _config["movie_template"]

    try:
        relative = template.format(
            type=type_label,
            title=title,
            series_title=s_title,
            year=year if year else "未知",
            season=season,
            episode=episode,
            ext=ext,
            quality=quality,
            video_codec=video_codec,
            tmdb_id=tmdb_id,
        )
    except (KeyError, ValueError) as e:
        logger.warning("[category] 模板格式化失败: %s", e)
        return _fallback(item, output_dir)

    # 清理每段路径
    parts = PurePosixPath(relative).parts
    cleaned = [_sanitize(p) for p in parts]
    relative = str(PurePosixPath(*cleaned)) if cleaned else "Unknown.strm"

    if not relative.lower().endswith(".strm"):
        relative = str(PurePosixPath(relative).with_suffix(".strm"))

    root = output_dir or "./config/strm"
    return str(PurePosixPath(root) / relative)


def _fallback(item, output_dir: str = "") -> str:
    """回退：保持原始路径结构"""
    root = output_dir or "./config/strm"
    fp = getattr(item, "file_path", "") or ""
    return str(PurePosixPath(root) / PurePosixPath(fp.lstrip("/")).with_suffix(".strm"))


# ── 预览（供前端显示模板效果）──

def preview_movie(title: str = "示例电影", year: int = 2024) -> str:
    class _F:
        item_type = "Movie"
        file_path = f"/data/{title}.mkv"
        video_codec = ""
        tmdb_id = 0
    _F.title = title
    _F.year = year
    _F.season_num = 0
    _F.episode_num = 0
    return resolve_path(_F())


def preview_episode(series: str = "示例剧集", year: int = 2024, s: int = 1, e: int = 1) -> str:
    class _F:
        item_type = "Episode"
        file_path = f"/data/{series}/S01E01.mkv"
        video_codec = ""
        tmdb_id = 0
    _F.title = f"第{e}集"
    _F.year = year
    _F.season_num = s
    _F.episode_num = e
    return resolve_path(_F(), series_title=series)

