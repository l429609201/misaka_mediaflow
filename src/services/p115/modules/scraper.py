# src/services/p115/modules/scraper.py
# STRM 刮削模块
#
# 职责：
#   根据 STRM 文件路径识别媒体类型（电影/剧集），调用 TMDB 接口获取元数据，
#   生成 .nfo / poster.jpg 等刮削产物，写入 STRM 文件同目录。
#
# 架构：
#   · Scraper          — 对外入口，供 strm_sync_service 调用
#   · _parse_media_name— 从文件名/路径解析媒体名称和年份
#   · _write_movie_nfo — 写电影 NFO（Kodi/Emby 格式）
#   · _write_tv_nfo    — 写剧集 NFO（含季集信息）
#   · _write_episode_group_nfo — 写剧集组 NFO
#   · _download_image  — 下载 poster/backdrop 图片
#
# 剧集组（EpisodeGroup）：
#   TMDB 剧集组定义了 Absolute / DVD / Story Arc 等多种集数排列方式。
#   当用户在配置中指定了 episode_group_id 时，使用剧集组中的排列顺序
#   生成集信息（解决动漫等绝对集数顺序问题）。

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

logger = logging.getLogger(__name__)

# 匹配常见命名规范（含年份、季集信息）
_RE_YEAR       = re.compile(r"\((\d{4})\)|\.(\d{4})\.")
_RE_SEASON_EP  = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})")
_RE_CLEAN      = re.compile(r"[\.\-_]")

# TMDB 图片 CDN
_IMAGE_BASE = "https://image.tmdb.org/t/p"


# ─────────────────────────────────────────────────────────────────────────────
#  辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _parse_media_name(strm_path: Path) -> tuple[str, int, Optional[int], Optional[int]]:
    """
    从 STRM 文件路径解析媒体信息。

    Returns:
        (name, year, season, episode)
        season/episode 为 None 表示电影；有值表示剧集。
    """
    stem = strm_path.stem  # 去掉 .strm 后缀
    year = 0

    # 提取年份
    m = _RE_YEAR.search(stem)
    if m:
        year = int(m.group(1) or m.group(2))

    # 提取季集号（剧集）
    se = _RE_SEASON_EP.search(stem)
    season  = int(se.group(1)) if se else None
    episode = int(se.group(2)) if se else None

    # 清理名称：去掉 SxxExx、年份、分隔符等
    name = stem
    name = _RE_SEASON_EP.sub("", name)
    name = _RE_YEAR.sub("", name)
    name = _RE_CLEAN.sub(" ", name).strip()

    # 如果 stem 解析不出名称，尝试父目录名
    if not name and strm_path.parent.name:
        name = _RE_CLEAN.sub(" ", strm_path.parent.name).strip()

    return name, year, season, episode


def _xml_pretty(root: Element) -> str:
    """生成格式化的 XML 字符串（Kodi/Emby NFO 格式）"""
    raw = tostring(root, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding=None)


def _write_nfo(path: Path, content: str) -> bool:
    """写 NFO 文件，已存在则跳过（overwrite=False 时）"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        logger.error("[Scraper] 写 NFO 失败 %s: %s", path, e)
        return False


async def _download_image(url: str, dest: Path) -> bool:
    """下载图片到本地，已存在则跳过"""
    if dest.exists():
        return True
    try:
        from src.core.http_proxy import proxy_client
        async with proxy_client(target_url=url, timeout=30) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(resp.content)
                return True
        logger.warning("[Scraper] 图片下载失败 HTTP %d: %s", resp.status_code, url)
    except Exception as e:
        logger.error("[Scraper] 图片下载异常 %s: %s", url, e)
    return False


def _image_url(path: str, size: str = "w500") -> str:
    if not path:
        return ""
    base = _IMAGE_BASE
    return f"{base}/{size}{path}"




# ─────────────────────────────────────────────────────────────────────────────
#  NFO 生成器
# ─────────────────────────────────────────────────────────────────────────────

def _build_movie_nfo(detail: dict) -> str:
    """生成电影 NFO（Kodi/Emby 兼容格式）"""
    root = Element("movie")
    SubElement(root, "title").text         = detail.get("title", "")
    SubElement(root, "originaltitle").text = detail.get("original_title", "")
    SubElement(root, "sorttitle").text     = detail.get("title", "")
    SubElement(root, "plot").text          = detail.get("overview", "")
    SubElement(root, "year").text          = (detail.get("release_date") or "")[:4]
    SubElement(root, "rating").text        = str(detail.get("vote_average", ""))
    SubElement(root, "votes").text         = str(detail.get("vote_count", ""))
    SubElement(root, "runtime").text       = str(detail.get("runtime") or "")
    SubElement(root, "tmdbid").text        = str(detail.get("id", ""))
    SubElement(root, "imdbid").text        = (detail.get("external_ids") or {}).get("imdb_id", "")
    SubElement(root, "tagline").text       = detail.get("tagline", "")
    SubElement(root, "status").text        = detail.get("status", "")
    for genre in (detail.get("genres") or []):
        SubElement(root, "genre").text = genre.get("name", "")
    for country in (detail.get("production_countries") or []):
        SubElement(root, "country").text = country.get("name", "")
    credits = detail.get("credits") or {}
    for cast in (credits.get("cast") or [])[:10]:
        actor = SubElement(root, "actor")
        SubElement(actor, "name").text  = cast.get("name", "")
        SubElement(actor, "role").text  = cast.get("character", "")
        SubElement(actor, "order").text = str(cast.get("order", ""))
        if cast.get("profile_path"):
            SubElement(actor, "thumb").text = _image_url(cast["profile_path"], "w185")
    return _xml_pretty(root)


def _build_tv_nfo(detail: dict) -> str:
    """生成剧集 NFO（tvshow.nfo 格式）"""
    root = Element("tvshow")
    SubElement(root, "title").text         = detail.get("name", "")
    SubElement(root, "originaltitle").text = detail.get("original_name", "")
    SubElement(root, "plot").text          = detail.get("overview", "")
    SubElement(root, "year").text          = (detail.get("first_air_date") or "")[:4]
    SubElement(root, "rating").text        = str(detail.get("vote_average", ""))
    SubElement(root, "votes").text         = str(detail.get("vote_count", ""))
    SubElement(root, "tmdbid").text        = str(detail.get("id", ""))
    SubElement(root, "imdbid").text        = (detail.get("external_ids") or {}).get("imdb_id", "")
    SubElement(root, "status").text        = detail.get("status", "")
    cr = detail.get("content_ratings") or {}
    for r in (cr.get("results") or []):
        if r.get("iso_3166_1") in ("CN", "US"):
            SubElement(root, "mpaa").text = r.get("rating", "")
            break
    for genre in (detail.get("genres") or []):
        SubElement(root, "genre").text = genre.get("name", "")
    for country in (detail.get("origin_country") or []):
        SubElement(root, "country").text = country
    credits = detail.get("credits") or {}
    for cast in (credits.get("cast") or [])[:10]:
        actor = SubElement(root, "actor")
        SubElement(actor, "name").text  = cast.get("name", "")
        SubElement(actor, "role").text  = cast.get("character", "")
        SubElement(actor, "order").text = str(cast.get("order", ""))
        if cast.get("profile_path"):
            SubElement(actor, "thumb").text = _image_url(cast["profile_path"], "w185")
    return _xml_pretty(root)


def _build_episode_nfo(ep_detail: dict, tv_detail: dict) -> str:
    """生成单集 NFO（episodedetails 格式）"""
    root = Element("episodedetails")
    SubElement(root, "title").text     = ep_detail.get("name", "")
    SubElement(root, "showtitle").text = tv_detail.get("name", "")
    SubElement(root, "plot").text      = ep_detail.get("overview", "")
    SubElement(root, "season").text    = str(ep_detail.get("season_number", ""))
    SubElement(root, "episode").text   = str(ep_detail.get("episode_number", ""))
    SubElement(root, "aired").text     = ep_detail.get("air_date", "")
    SubElement(root, "rating").text    = str(ep_detail.get("vote_average", ""))
    SubElement(root, "tmdbid").text    = str(ep_detail.get("id", ""))
    for crew in (ep_detail.get("crew") or []):
        if crew.get("job") == "Director":
            SubElement(root, "director").text = crew.get("name", "")
    return _xml_pretty(root)


def _build_episode_group_nfo(group: dict, tv_detail: dict) -> str:
    """生成剧集组 NFO（描述剧集组排列方式，附各子分组 episode 列表）"""
    root = Element("episodegroup")
    SubElement(root, "id").text          = group.get("id", "")
    SubElement(root, "name").text        = group.get("name", "")
    SubElement(root, "type_label").text  = group.get("type_label", "")
    SubElement(root, "description").text = group.get("description", "")
    SubElement(root, "showtitle").text   = tv_detail.get("name", "")
    SubElement(root, "tmdbid").text      = str(tv_detail.get("id", ""))
    for grp in (group.get("groups") or []):
        season_el = SubElement(root, "season")
        SubElement(season_el, "order").text = str(grp.get("order", ""))
        SubElement(season_el, "name").text  = grp.get("name", "")
        for ep in (grp.get("episodes") or []):
            ep_el = SubElement(season_el, "episode")
            SubElement(ep_el, "order").text          = str(ep.get("order", ""))
            SubElement(ep_el, "episode_number").text = str(ep.get("episode_number", ""))
            SubElement(ep_el, "season_number").text  = str(ep.get("season_number", ""))
            SubElement(ep_el, "name").text           = ep.get("name", "")
    return _xml_pretty(root)



# ─────────────────────────────────────────────────────────────────────────────
#  Scraper 主类 — 对外入口
# ─────────────────────────────────────────────────────────────────────────────

class Scraper:
    """
    STRM 刮削器。

    使用方式：
        scraper = Scraper(tmdb_provider, episode_group_id="xxxx")
        await scraper.scrape_file(Path("/data/strm/影音/电影/盗梦空间 (2010).strm"))
        await scraper.scrape_dir(Path("/data/strm/影音"))  # 批量刮削整个目录

    episode_group_id：
        若指定，剧集将以剧集组的 season/episode 顺序写 NFO（用于绝对集数等场景）。
        可在前端配置，留空则走标准 SxxExx 路径。
    """

    def __init__(self, tmdb, episode_group_id: str = "", download_images: bool = True):
        self._tmdb              = tmdb            # TMDBProvider 实例
        self._episode_group_id  = episode_group_id
        self._download_images   = download_images
        self._tv_cache: dict[int, dict]  = {}    # tmdb_id → tv detail（避免重复请求）
        self._eg_cache: Optional[dict]   = None  # 剧集组详情缓存

    # ── 单文件刮削入口 ────────────────────────────────────────────────────────

    async def scrape_file(self, strm_path: Path) -> bool:
        """刮削单个 STRM 文件，在同目录写 NFO + 图片"""
        name, year, season, episode = _parse_media_name(strm_path)
        if not name:
            logger.warning("[Scraper] 无法解析媒体名称: %s", strm_path)
            return False

        if season is not None and episode is not None:
            return await self._scrape_episode(strm_path, name, year, season, episode)
        else:
            return await self._scrape_movie(strm_path, name, year)

    # ── 批量刮削入口 ─────────────────────────────────────────────────────────

    async def scrape_dir(self, strm_root: Path, concurrency: int = 3) -> dict:
        """递归刮削 strm_root 下所有 .strm 文件（并发度 concurrency）"""
        files = list(strm_root.rglob("*.strm"))
        logger.info("[Scraper] 开始批量刮削 %d 个文件: %s", len(files), strm_root)
        sem = asyncio.Semaphore(concurrency)
        stats = {"total": len(files), "ok": 0, "skip": 0, "error": 0}

        async def _one(f: Path):
            async with sem:
                try:
                    ok = await self.scrape_file(f)
                    if ok:
                        stats["ok"] += 1
                    else:
                        stats["skip"] += 1
                except Exception as e:
                    logger.error("[Scraper] 刮削异常 %s: %s", f, e)
                    stats["error"] += 1

        await asyncio.gather(*[_one(f) for f in files])
        logger.info("[Scraper] 批量刮削完成: %s", stats)
        return stats

    # ── 电影刮削 ─────────────────────────────────────────────────────────────

    async def _scrape_movie(self, strm_path: Path, name: str, year: int) -> bool:
        nfo_path = strm_path.with_suffix(".nfo")
        if nfo_path.exists():
            return True  # 已刮削，跳过

        results = await self._tmdb.search_movie(name, year)
        if not results:
            logger.warning("[Scraper] 电影未找到: %s (%d)", name, year)
            return False

        tmdb_id = results[0]["id"]
        detail  = await self._tmdb.get_movie(tmdb_id)
        if not detail:
            return False

        nfo_content = _build_movie_nfo(detail)
        _write_nfo(nfo_path, nfo_content)
        logger.info("[Scraper] 电影 NFO 已写入: %s", nfo_path)

        if self._download_images:
            await self._save_movie_images(detail, strm_path.parent)

        return True

    # ── 剧集刮削 ─────────────────────────────────────────────────────────────

    async def _scrape_episode(
        self, strm_path: Path, name: str, year: int, season: int, episode: int
    ) -> bool:
        nfo_path = strm_path.with_suffix(".nfo")
        if nfo_path.exists():
            return True  # 已刮削，跳过

        # 1) 查剧集主信息
        tv_detail = await self._get_tv(name, year)
        if not tv_detail:
            logger.warning("[Scraper] 剧集未找到: %s (%d)", name, year)
            return False
        tmdb_id = tv_detail["id"]

        # 2) 剧集组模式：用剧集组映射 season/episode
        if self._episode_group_id:
            eg = await self._get_episode_group()
            if eg:
                mapped = _map_episode_via_group(eg, season, episode)
                if mapped:
                    season, episode = mapped
                    logger.debug("[Scraper] 剧集组映射: S%02dE%03d", season, episode)

        # 3) 获取单集详情
        ep_detail = await self._tmdb.get_tv_episode(tmdb_id, season, episode)
        if not ep_detail:
            logger.warning("[Scraper] 单集未找到 S%02dE%03d: %s", season, episode, name)
            return False

        # 4) 写 tvshow.nfo（剧集根目录）+ episode NFO（当前文件）
        show_dir = _find_show_dir(strm_path)
        tvshow_nfo = show_dir / "tvshow.nfo"
        if not tvshow_nfo.exists():
            _write_nfo(tvshow_nfo, _build_tv_nfo(tv_detail))
            logger.info("[Scraper] tvshow.nfo 已写入: %s", tvshow_nfo)
            if self._download_images:
                await self._save_tv_images(tv_detail, show_dir)

        # 5) 写剧集组 NFO（若启用）
        if self._episode_group_id:
            eg = await self._get_episode_group()
            if eg:
                eg_nfo = show_dir / "episodegroup.nfo"
                if not eg_nfo.exists():
                    _write_nfo(eg_nfo, _build_episode_group_nfo(eg, tv_detail))
                    logger.info("[Scraper] 剧集组 NFO 已写入: %s", eg_nfo)

        # 6) 写 episode NFO
        _write_nfo(nfo_path, _build_episode_nfo(ep_detail, tv_detail))
        logger.info("[Scraper] episode NFO 已写入: %s", nfo_path)
        return True

    # ── 内部辅助 ─────────────────────────────────────────────────────────────

    async def _get_tv(self, name: str, year: int) -> Optional[dict]:
        """搜索剧集并缓存 detail"""
        results = await self._tmdb.search_tv(name, year)
        if not results:
            return None
        tmdb_id = results[0]["id"]
        if tmdb_id not in self._tv_cache:
            self._tv_cache[tmdb_id] = await self._tmdb.get_tv(tmdb_id)
        return self._tv_cache.get(tmdb_id)

    async def _get_episode_group(self) -> Optional[dict]:
        """获取并缓存剧集组详情"""
        if self._eg_cache is None and self._episode_group_id:
            self._eg_cache = await self._tmdb.get_episode_group_detail(self._episode_group_id)
        return self._eg_cache

    async def _save_movie_images(self, detail: dict, dest_dir: Path):
        for fname, path_key, size in [
            ("poster.jpg",   "poster_path",   "w500"),
            ("backdrop.jpg", "backdrop_path", "w1280"),
        ]:
            img_path = detail.get(path_key)
            if img_path:
                await _download_image(_image_url(img_path, size), dest_dir / fname)

    async def _save_tv_images(self, detail: dict, dest_dir: Path):
        for fname, path_key, size in [
            ("poster.jpg",   "poster_path",   "w500"),
            ("backdrop.jpg", "backdrop_path", "w1280"),
        ]:
            img_path = detail.get(path_key)
            if img_path:
                await _download_image(_image_url(img_path, size), dest_dir / fname)


# ─────────────────────────────────────────────────────────────────────────────
#  工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _find_show_dir(episode_path: Path) -> Path:
    """
    从集文件路径向上找剧集根目录。
    约定：集文件在 <show_dir>/<season_dir>/<episode>.strm，
    因此最多上溯 2 级。
    """
    p = episode_path.parent  # season 目录
    if p.parent and p.parent != p:
        return p.parent       # show 目录
    return p


def _map_episode_via_group(group: dict, season: int, episode: int) -> Optional[tuple[int, int]]:
    """
    在剧集组中查找 order=season 的子分组，找到 order=episode 的集条目，
    返回对应的 (season_number, episode_number)（TMDB 标准集数）。
    """
    for grp in (group.get("groups") or []):
        if grp.get("order") == season:
            for ep in (grp.get("episodes") or []):
                if ep.get("order") == episode:
                    return ep.get("season_number"), ep.get("episode_number")
    return None
