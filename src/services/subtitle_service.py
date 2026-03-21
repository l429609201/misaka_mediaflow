# src/services/subtitle_service.py
# 字幕子集化服务
#
# 功能：
#   1. 外置 fontInAss 接入：将 ASS 字幕请求转发给外部 fontInAss 服务做子集化
#   2. 内封字幕提取（可选开关，默认关闭）：
#      - 302 成功后异步触发，用 Range 请求从 115 CDN 拉取 MKV 关键段落
#      - 提取内封 ASS 字幕并缓存，供下次播放命中
#
# 配置项（SystemConfig 表）：
#   font_in_ass_enabled   : "true" / "false"  是否启用 fontInAss
#   font_in_ass_url       : fontInAss 服务地址，如 http://fontinass:8011
#   embedded_sub_enabled  : "true" / "false"  是否启用内封字幕提取（默认 false）
#   embedded_sub_tracks   : JSON 数组，字幕轨道匹配偏好，如 ["zh","chi","chs","cht"]
#                           按顺序匹配 ffprobe 输出的 Language 字段，取第一个命中的
#                           留空表示取第一条字幕轨道

import asyncio
import json
import logging
import re
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── 内存配置缓存（避免每次请求都查 DB）────────────────────────────────────────
_cfg_cache: dict = {}
_cfg_cache_at: float = 0.0
_CFG_CACHE_TTL = 60  # 秒

# ── 内封字幕内存缓存（item_id → 字幕内容字节）──────────────────────────────────
# 使用简单 dict + TTL，避免引入额外依赖
_sub_cache: dict[str, tuple[bytes, float]] = {}  # {item_id: (data, expire_ts)}
_SUB_CACHE_TTL = 3600 * 6  # 6 小时
_sub_extracting: set[str] = set()  # 正在提取中的 item_id

# ── 无字幕负缓存（item_id → expire_ts）────────────────────────────────────────
# 对【确认没有内封字幕轨道】的文件记录 TTL，避免每次播放都重跑 ffprobe
_sub_no_track: dict[str, float] = {}  # {item_id: expire_ts}
_SUB_NO_TRACK_TTL = 3600 * 2  # 2 小时

# ── ffprobe 失败冷却期（item_id → expire_ts）──────────────────────────────────
# 与 _sub_no_track 严格分离：
#   _sub_no_track  = ffprobe 成功但确认无字幕轨道（语义明确）
#   _sub_probe_fail = ffprobe 本身失败/超时（可能是临时问题，冷却后允许重试）
_sub_probe_fail: dict[str, float] = {}  # {item_id: expire_ts}
_SUB_PROBE_FAIL_TTL = 60  # 60 秒冷却，避免并发刷屏，但不长期封锁


# ── 配置读取 ──────────────────────────────────────────────────────────────────

async def _load_config() -> dict:
    """从数据库读取字幕服务配置（带 60s TTL 缓存）"""
    global _cfg_cache, _cfg_cache_at
    now = time.monotonic()
    if _cfg_cache and (now - _cfg_cache_at) < _CFG_CACHE_TTL:
        return _cfg_cache

    try:
        from src.db import get_async_session_local
        from src.db.models import SystemConfig
        from sqlalchemy import select

        keys = [
            "font_in_ass_enabled",
            "font_in_ass_url",
            "subtitle_engine",           # "builtin" | "external"（默认 external）
            "embedded_sub_enabled",
            "embedded_sub_tracks",
            "embedded_sub_include_movies",
        ]
        result = {}
        async with get_async_session_local() as db:
            for k in keys:
                row = await db.execute(select(SystemConfig).where(SystemConfig.key == k))
                cfg = row.scalars().first()
                result[k] = cfg.value if cfg else ""

        _cfg_cache = result
        _cfg_cache_at = now
        return result
    except Exception as e:
        logger.debug("[subtitle] 配置加载失败: %s", e)
        return _cfg_cache or {}


def invalidate_config_cache() -> None:
    """外部调用（保存配置后）使缓存立即失效"""
    global _cfg_cache_at
    _cfg_cache_at = 0.0


# ── 公开接口：内封字幕 → fontInAss 子集化 ────────────────────────────────────

async def process_embedded_sub_with_font_in_ass(
    item_id: str,
    sub_bytes: bytes,
) -> Optional[bytes]:
    """
    将已提取的内封字幕字节直接 POST 给 fontInAss /fontinass/process_bytes 接口做子集化。

    fontInAss 的 /fontinass/process_bytes 接口：
      - 请求：POST，body 为原始 ASS/SRT 字节
      - 响应：body 为子集化后的字节，header X-Code=0 表示成功

    Returns:
        子集化后的字节，或 None（未启用 / 失败时降级返回原始内容）
    """
    cfg = await _load_config()
    if cfg.get("font_in_ass_enabled", "").lower() != "true":
        return None

    base_url = (cfg.get("font_in_ass_url") or "").rstrip("/")
    if not base_url:
        return None

    target = f"{base_url}/fontinass/process_bytes"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                target,
                content=sub_bytes,
                headers={"Content-Type": "application/octet-stream"},
            )
            import base64 as _b64
            x_code = resp.headers.get("X-Code", "")
            # error header: base64 编码的字体缺失信息
            error_raw = resp.headers.get("error", "")
            error_msg = ""
            if error_raw:
                try:
                    error_msg = _b64.b64decode(error_raw).decode("utf-8", errors="replace").strip()
                except Exception:
                    error_msg = error_raw
            logger.debug(
                "[subtitle] fontInAss(内封) 响应: status=%d X-Code=%s input=%d bytes output=%d bytes",
                resp.status_code, x_code, len(sub_bytes), len(resp.content),
            )
            if x_code not in ("", "0"):
                logger.warning("[subtitle] fontInAss 内封字幕处理失败: X-Code=%s item_id=%s", x_code, item_id)
                return None
            if len(resp.content) == 0:
                logger.warning("[subtitle] fontInAss 内封字幕返回空内容(X-Code=%s) item_id=%s", x_code, item_id)
                return None
            if error_msg:
                logger.warning("[subtitle] fontInAss 字体缺失(内封): item_id=%s\n%s", item_id, error_msg)
            logger.info(
                "[subtitle] 内封字幕 fontInAss 子集化完成: item_id=%s %d bytes → %d bytes",
                item_id, len(sub_bytes), len(resp.content),
            )
            return resp.content
    except Exception as e:
        logger.warning("[subtitle] fontInAss process_bytes 失败: %s item_id=%s", e, item_id)
        return None


# ── 公开接口：fontInAss 转发（nginx 模式）─────────────────────────────────────

async def proxy_to_font_in_ass(
    original_path: str,
    query_string: str,
    request_headers: dict,
) -> Optional[tuple[int, bytes, dict]]:
    """
    字幕子集化主路由（nginx 模式）：
      1. 从 Emby 拉取原始字幕内容
      2. 根据 subtitle_engine 配置选择处理引擎：
         - builtin : 内置 fonttools 引擎（无需外部服务）
         - external: 转发给外置 fontInAss process_bytes（默认）
      3. 返回处理后的字幕给播放器，失败时降级返回原始内容
    """
    cfg = await _load_config()
    if cfg.get("font_in_ass_enabled", "").lower() != "true":
        return None

    engine = cfg.get("subtitle_engine", "external").strip().lower()  # builtin / external

    # 外置引擎额外检查 URL
    if engine != "builtin":
        base_url = (cfg.get("font_in_ass_url") or "").rstrip("/")
        if not base_url:
            logger.warning("[subtitle] 外置引擎已启用但未配置 fontInAss 地址")
            return None

    # ── Step1: 获取 Emby 地址 ────────────────────────────────────────────────
    emby_host = await _get_emby_host()
    if not emby_host:
        logger.warning("[subtitle] 无法获取 Emby 地址，字幕子集化无法工作")
        return None

    # ── Step2: 从 Emby 拉取原始字幕内容 ─────────────────────────────────────
    emby_url = f"{emby_host}{original_path}"
    if query_string:
        emby_url = f"{emby_url}?{query_string}"

    forward_headers = {}
    for h in ("authorization", "x-emby-token", "x-emby-authorization", "cookie"):
        v = request_headers.get(h) or request_headers.get(h.title())
        if v:
            forward_headers[h] = v

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            emby_resp = await client.get(emby_url, headers=forward_headers, follow_redirects=True)
            if emby_resp.status_code != 200:
                logger.warning("[subtitle] 从 Emby 拉取字幕失败: status=%d url=%s",
                               emby_resp.status_code, emby_url)
                return None
            sub_bytes = emby_resp.content
            if not sub_bytes:
                logger.warning("[subtitle] Emby 返回空字幕: url=%s", emby_url)
                return None
            logger.info("[subtitle] 从 Emby 拉取字幕成功: path=%s size=%d bytes",
                        original_path, len(sub_bytes))
    except Exception as e:
        logger.warning("[subtitle] 从 Emby 拉取字幕异常: %s (url=%s)", e, emby_url)
        return None

    # ── Step3A: 内置引擎 ──────────────────────────────────────────────────────
    if engine == "builtin":
        return await _process_with_builtin(sub_bytes, original_path)

    # ── Step3B: 外置引擎（fontInAss process_bytes）───────────────────────────
    return await _process_with_external(sub_bytes, original_path, base_url)


async def _process_with_builtin(
    sub_bytes: bytes,
    original_path: str,
) -> tuple:
    """调用内置 fonttools 引擎处理字幕（支持 ASS/SRT/VTT/其他）"""
    try:
        from src.services.subtitle_builtin import process_subtitle_builtin
        result_bytes, missing, content_type = await process_subtitle_builtin(sub_bytes)
        if missing:
            logger.warning("[subtitle] 内置引擎字体缺失: path=%s 缺失=%s",
                           original_path, missing)
        logger.info("[subtitle] 内置引擎完成: %d bytes -> %d bytes path=%s",
                    len(sub_bytes), len(result_bytes), original_path)
        return 200, result_bytes, {"content-type": content_type}
    except Exception as e:
        logger.warning("[subtitle] 内置引擎异常: %s path=%s", e, original_path)
        return 200, sub_bytes, {"content-type": "text/plain; charset=utf-8"}


async def _process_with_external(
    sub_bytes: bytes,
    original_path: str,
    base_url: str,
) -> tuple[int, bytes, dict]:
    """调用外置 fontInAss process_bytes 接口处理字幕"""
    import base64 as _b64
    process_url = f"{base_url}/fontinass/process_bytes"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            fa_resp = await client.post(
                process_url,
                content=sub_bytes,
                headers={"Content-Type": "application/octet-stream"},
            )
        x_code = fa_resp.headers.get("X-Code", "")
        error_raw = fa_resp.headers.get("error", "")
        error_msg = ""
        if error_raw:
            try:
                error_msg = _b64.b64decode(error_raw).decode("utf-8", errors="replace").strip()
            except Exception:
                error_msg = error_raw

        logger.debug("[subtitle] fontInAss 响应: status=%d X-Code=%s %d→%d bytes",
                     fa_resp.status_code, x_code, len(sub_bytes), len(fa_resp.content))

        if x_code not in ("", "0"):
            logger.warning("[subtitle] fontInAss 失败: X-Code=%s path=%s", x_code, original_path)
            return 200, sub_bytes, {"content-type": "text/plain; charset=utf-8"}

        result_bytes = fa_resp.content
        if not result_bytes:
            logger.warning("[subtitle] fontInAss 返回空内容，降级: path=%s", original_path)
            return 200, sub_bytes, {"content-type": "text/plain; charset=utf-8"}

        if error_msg:
            logger.warning("[subtitle] fontInAss 字体缺失: path=%s\n%s", original_path, error_msg)

        logger.info("[subtitle] 外置引擎完成: %d bytes -> %d bytes path=%s",
                    len(sub_bytes), len(result_bytes), original_path)
        resp_headers = {k: v for k, v in fa_resp.headers.items()
                        if k.lower() in ("content-type", "content-encoding")}
        if "content-type" not in {k.lower() for k in resp_headers}:
            resp_headers["content-type"] = "text/x-ssa; charset=utf-8"
        return 200, result_bytes, resp_headers
    except Exception as e:
        logger.warning("[subtitle] fontInAss process_bytes 异常: %s path=%s", e, original_path)
        return 200, sub_bytes, {"content-type": "text/plain; charset=utf-8"}


async def _get_emby_host() -> str:
    """从 SystemConfig 或 settings 获取 Emby 服务地址"""
    try:
        from src.db import get_async_session_local
        from src.db.models import SystemConfig
        from sqlalchemy import select

        async with get_async_session_local() as db:
            row = await db.execute(
                select(SystemConfig).where(SystemConfig.key == "media_server_host")
            )
            cfg = row.scalars().first()
            if cfg and cfg.value:
                return cfg.value.rstrip("/")
    except Exception as e:
        logger.debug("[subtitle] 从 DB 获取 Emby 地址失败: %s", e)

    # 降级读 settings
    try:
        from src.core.config import settings
        return (settings.media_server.host or "").rstrip("/")
    except Exception:
        return ""


# ── 公开接口：内封字幕缓存查询 ────────────────────────────────────────────────

def get_cached_embedded_sub(item_id: str) -> Optional[bytes]:
    """从内存缓存读取已提取的内封字幕。未命中或已过期返回 None。"""
    entry = _sub_cache.get(item_id)
    if not entry:
        return None
    data, expire_ts = entry
    if time.monotonic() > expire_ts:
        _sub_cache.pop(item_id, None)
        return None
    return data


def _set_cached_embedded_sub(item_id: str, data: bytes) -> None:
    """写入内封字幕缓存"""
    _sub_cache[item_id] = (data, time.monotonic() + _SUB_CACHE_TTL)
    logger.info("[subtitle] 内封字幕已缓存: item_id=%s size=%d bytes", item_id, len(data))


# ── 公开接口：触发内封字幕异步提取 ───────────────────────────────────────────

async def trigger_embedded_sub_extraction(
    item_id: str,
    cdn_url: str,
    user_agent: str = "",
    item_type: str = "",
) -> None:
    """
    302 成功后异步触发内封字幕提取，不阻塞主流程。
    - 若开关未开启，直接返回
    - 若该 item_id 已有缓存、正在提取中、或已确认无字幕轨道，跳过
    - item_type: Emby 的 Type 字段，如 "Movie" / "Episode"
      默认只对剧集(Episode)生效；开启 embedded_sub_include_movies 后对电影也生效
    """
    cfg = await _load_config()
    if cfg.get("embedded_sub_enabled", "").lower() != "true":
        return

    # ── 电影类型过滤 ────────────────────────────────────────────────────────
    # item_type 为空时（兼容旧版 Go 未传）不过滤，保持原有行为
    if item_type:
        is_movie = item_type.lower() == "movie"
        include_movies = cfg.get("embedded_sub_include_movies", "").lower() == "true"
        if is_movie and not include_movies:
            logger.debug("[subtitle] 电影类型跳过内封字幕提取(未开启对电影生效): item_id=%s", item_id)
            return

    if item_id in _sub_extracting:
        logger.debug("[subtitle] 已在提取中，跳过: item_id=%s", item_id)
        return

    if get_cached_embedded_sub(item_id) is not None:
        logger.debug("[subtitle] 缓存已存在，跳过提取: item_id=%s", item_id)
        return

    # 检查负缓存：已确认此文件无内封字幕
    no_track_expire = _sub_no_track.get(item_id)
    if no_track_expire and time.monotonic() < no_track_expire:
        logger.debug("[subtitle] 已确认无内封字幕，跳过: item_id=%s", item_id)
        return

    # 检查 ffprobe 失败冷却期（与"无字幕"语义分离，冷却结束后允许重试）
    probe_fail_expire = _sub_probe_fail.get(item_id)
    if probe_fail_expire and time.monotonic() < probe_fail_expire:
        logger.debug("[subtitle] ffprobe 失败冷却中，跳过: item_id=%s", item_id)
        return

    track_prefs_raw = cfg.get("embedded_sub_tracks", "")
    try:
        track_prefs: list[str] = json.loads(track_prefs_raw) if track_prefs_raw else []
    except Exception:
        track_prefs = []

    # fire-and-forget
    asyncio.create_task(
        _extract_embedded_sub(item_id, cdn_url, user_agent, track_prefs),
        name=f"embedded_sub_{item_id}",
    )


# ── 内封字幕提取核心（异步，后台运行）────────────────────────────────────────

async def _extract_embedded_sub(
    item_id: str,
    cdn_url: str,
    user_agent: str,
    track_prefs: list[str],
) -> None:
    """
    通过 ffprobe + ffmpeg 从 115 CDN 直链提取内封字幕。

    流程：
      1. ffprobe 探测字幕轨道（只读文件头，<1MB 流量）
      2. 按 track_prefs 匹配语言偏好，取第一个命中的；无偏好则取第一条
      3. ffmpeg 提取该轨道为 .ass 文件（利用 MKV Cues 做 Range 跳读）
      4. 缓存结果
    """
    if item_id in _sub_extracting:
        return
    _sub_extracting.add(item_id)
    t0 = time.monotonic()
    logger.info("[subtitle] 开始内封字幕提取: item_id=%s", item_id)

    try:
        import shutil, tempfile, os

        if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
            logger.warning("[subtitle] ffprobe/ffmpeg 未找到，内封字幕提取不可用")
            return

        # ── Step1: ffprobe 探测字幕轨道 ─────────────────────────────────────
        logger.debug("[subtitle] ffprobe 目标 URL: %s", cdn_url[:120] if cdn_url else "None")
        probe_cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-select_streams", "s",
            "-user_agent", user_agent or "Mozilla/5.0",
            cdn_url,
        ]
        try:
            probe_proc = await asyncio.create_subprocess_exec(
                *probe_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(probe_proc.communicate(), timeout=30)
            if stderr:
                logger.debug("[subtitle] ffprobe stderr: %s",
                             stderr.decode("utf-8", errors="replace").strip()[:500])
            probe_data = json.loads(stdout.decode("utf-8", errors="replace"))
        except asyncio.TimeoutError:
            logger.warning("[subtitle] ffprobe 超时: item_id=%s", item_id)
            _sub_probe_fail[item_id] = time.monotonic() + _SUB_PROBE_FAIL_TTL
            return
        except Exception as e:
            logger.warning("[subtitle] ffprobe 失败: %s item_id=%s", e, item_id)
            _sub_probe_fail[item_id] = time.monotonic() + _SUB_PROBE_FAIL_TTL
            return

        streams = probe_data.get("streams", [])
        if not streams:
            logger.info("[subtitle] 未发现内封字幕轨道: item_id=%s", item_id)
            # 写入负缓存，避免该文件每次播放都重跑 ffprobe
            _sub_no_track[item_id] = time.monotonic() + _SUB_NO_TRACK_TTL
            return

        # ── Step2: 过滤图形字幕（PGS/VOBSUB/DVBSUB 等），只保留文本字幕 ────────
        # ffmpeg 无法将 bitmap 字幕转为 ASS，会报 "bitmap to bitmap" 错误
        BITMAP_CODECS = {"hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvbsub",
                         "dvb_subtitle", "xsub", "vobsub", "mov_text"}
        text_streams = [
            s for s in streams
            if s.get("codec_name", "").lower() not in BITMAP_CODECS
        ]
        if not text_streams:
            logger.info(
                "[subtitle] 内封字幕均为图形格式(PGS/VOBSUB等)，无法提取为ASS: item_id=%s codecs=%s",
                item_id,
                [s.get("codec_name") for s in streams],
            )
            # 写入负缓存，图形字幕永远无法提取，不必重试
            _sub_no_track[item_id] = time.monotonic() + _SUB_NO_TRACK_TTL
            return

        chosen_index: Optional[int] = None  # ffmpeg stream index (0:s:N)
        chosen_lang = ""

        if track_prefs:
            for pref in track_prefs:
                pref_lower = pref.lower()
                for s in text_streams:
                    lang = (s.get("tags", {}).get("language") or "").lower()
                    title = (s.get("tags", {}).get("title") or "").lower()
                    if pref_lower in (lang, title) or pref_lower in lang or pref_lower in title:
                        chosen_index = s.get("index")
                        chosen_lang = lang
                        break
                if chosen_index is not None:
                    break

        if chosen_index is None:
            # 无匹配偏好 → 取第一条文本字幕轨道
            s0 = text_streams[0]
            chosen_index = s0.get("index")
            chosen_lang = (s0.get("tags", {}).get("language") or "unknown")

        # ffmpeg 的 -map 0:N 用的是全局流索引，对于字幕可以用 0:s:0 等
        # 更稳妥：用 stream_specifier index 直接映射
        sub_stream_pos = next(
            (i for i, s in enumerate(streams) if s.get("index") == chosen_index), 0
        )

        logger.info(
            "[subtitle] 选择字幕轨道: item_id=%s stream_index=%s sub_pos=%d lang=%s",
            item_id, chosen_index, sub_stream_pos, chosen_lang,
        )

        # ── Step3: ffmpeg 提取为 .ass ────────────────────────────────────────
        with tempfile.TemporaryDirectory(prefix="mmf_sub_") as tmpdir:
            out_path = os.path.join(tmpdir, "sub.ass")
            extract_cmd = [
                "ffmpeg", "-v", "warning",
                "-user_agent", user_agent or "Mozilla/5.0",
                "-i", cdn_url,
                "-map", f"0:s:{sub_stream_pos}",
                "-c:s", "ass",
                "-y", out_path,
            ]
            try:
                ext_proc = await asyncio.create_subprocess_exec(
                    *extract_cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(ext_proc.communicate(), timeout=300)
                if ext_proc.returncode != 0:
                    err_msg = stderr.decode("utf-8", errors="replace")[-300:]
                    logger.warning(
                        "[subtitle] ffmpeg 提取失败(rc=%d): %s item_id=%s",
                        ext_proc.returncode, err_msg, item_id,
                    )
                    # 图形字幕导致的失败写入负缓存，避免反复重试
                    if "bitmap to bitmap" in err_msg or "Invalid argument" in err_msg:
                        _sub_no_track[item_id] = time.monotonic() + _SUB_NO_TRACK_TTL
                        logger.info("[subtitle] 图形字幕提取失败，写入负缓存: item_id=%s", item_id)
                    return
            except asyncio.TimeoutError:
                logger.warning("[subtitle] ffmpeg 提取超时(300s): item_id=%s", item_id)
                return
            except Exception as e:
                logger.warning("[subtitle] ffmpeg 提取异常: %s item_id=%s", e, item_id)
                return

            # 读取提取结果
            try:
                with open(out_path, "rb") as f:
                    sub_data = f.read()
            except Exception as e:
                logger.warning("[subtitle] 读取提取字幕失败: %s", e)
                return

        elapsed = time.monotonic() - t0
        logger.info(
            "[subtitle] 内封字幕提取完成: item_id=%s lang=%s size=%d bytes 耗时=%.1fs",
            item_id, chosen_lang, len(sub_data), elapsed,
        )

        # ── Step4: 尝试立即送 fontInAss 子集化，缓存处理后的结果 ────────────────
        # 内封字幕播放时播放器直接从视频流读取，不走 HTTP 字幕接口，
        # 所以无法在字幕请求时实时子集化，必须在提取阶段就预处理好。
        subsetted = await process_embedded_sub_with_font_in_ass(item_id, sub_data)
        if subsetted is not None:
            _set_cached_embedded_sub(item_id, subsetted)
            logger.info(
                "[subtitle] 内封字幕已子集化并缓存: item_id=%s %d bytes → %d bytes",
                item_id, len(sub_data), len(subsetted),
            )
        else:
            # fontInAss 未启用或失败，缓存原始 ASS（万一 Emby 发字幕请求也能命中）
            _set_cached_embedded_sub(item_id, sub_data)

    except Exception as e:
        logger.error("[subtitle] 内封字幕提取异常: %s item_id=%s", e, item_id)
    finally:
        _sub_extracting.discard(item_id)