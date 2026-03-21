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
_sub_cache: dict[str, tuple[bytes, float]] = {}       # {item_id: (data, expire_ts)}
_sub_cache_info: dict[str, dict] = {}                  # {item_id: {lang, title, codec}}
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
    外挂字幕子集化主路由：
      1. 从 Emby 拉取原始字幕内容
      2. 根据 subtitle_engine 配置选择处理引擎：
         - builtin : 内置 fonttools 引擎（无需外部服务）
         - external: 转发给外置 fontInAss process_bytes（默认）
      3. 返回处理后的字幕给播放器，失败时降级返回原始内容

    Returns None 表示子集化未启用或初始化失败（调用方应告知 Go 透传 Emby）。
    """
    cfg = await _load_config()

    # ── 检查总开关 ───────────────────────────────────────────────────────────
    if cfg.get("font_in_ass_enabled", "").lower() != "true":
        logger.info(
            "[subtitle] 字幕子集化未启用(font_in_ass_enabled != true)，透传 Emby。"
            " 如需子集化请在「系统设置 → 字幕」中开启。path=%s", original_path
        )
        return None

    engine = cfg.get("subtitle_engine", "external").strip().lower()  # builtin / external
    logger.info("[subtitle] 子集化引擎: %s path=%s", engine, original_path)

    # ── 外置引擎：检查 URL 配置 ──────────────────────────────────────────────
    base_url = ""
    if engine != "builtin":
        base_url = (cfg.get("font_in_ass_url") or "").rstrip("/")
        if not base_url:
            logger.warning(
                "[subtitle] 外置引擎已启用但未配置 fontInAss 地址(font_in_ass_url 为空)，透传 Emby。"
                " 请配置 fontInAss 服务地址或将引擎切换为 builtin。path=%s", original_path
            )
            return None
        logger.info("[subtitle] 外置 fontInAss 地址: %s", base_url)

    # ── Step1: 获取 Emby 地址 ────────────────────────────────────────────────
    emby_host = await _get_emby_host()
    if not emby_host:
        logger.warning("[subtitle] 无法获取 Emby 地址，字幕子集化无法工作。path=%s", original_path)
        return None

    # ── Step2: 从 Emby 拉取原始字幕内容 ─────────────────────────────────────
    emby_url = f"{emby_host}{original_path}"
    if query_string:
        emby_url = f"{emby_url}?{query_string}"

    logger.info("[subtitle] 从 Emby 拉取原始字幕: url=%s", emby_url)

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
            logger.info("[subtitle] ✅ 从 Emby 拉取字幕成功: %d bytes path=%s",
                        len(sub_bytes), original_path)
    except Exception as e:
        logger.warning("[subtitle] 从 Emby 拉取字幕异常: %s (url=%s)", e, emby_url)
        return None

    # ── Step3A: 内置引擎 ──────────────────────────────────────────────────────
    if engine == "builtin":
        logger.info("[subtitle] 调用内置 fonttools 引擎: path=%s", original_path)
        return await _process_with_builtin(sub_bytes, original_path)

    # ── Step3B: 外置引擎（fontInAss process_bytes）───────────────────────────
    logger.info("[subtitle] 调用外置 fontInAss 引擎: %s/fontinass/process_bytes path=%s",
                base_url, original_path)
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
        _sub_cache_info.pop(item_id, None)
        return None
    return data


def get_cached_embedded_sub_info(item_id: str) -> Optional[dict]:
    """返回已缓存的内封字幕元数据（lang/title/codec），未命中返回 None。"""
    if get_cached_embedded_sub(item_id) is None:
        return None
    return _sub_cache_info.get(item_id)


def _set_cached_embedded_sub(item_id: str, data: bytes, info: Optional[dict] = None) -> None:
    """写入内封字幕缓存，info 为字幕元数据 {lang, title, codec}"""
    _sub_cache[item_id] = (data, time.monotonic() + _SUB_CACHE_TTL)
    if info:
        _sub_cache_info[item_id] = info
    logger.info("[subtitle] 内封字幕已缓存: item_id=%s size=%d bytes lang=%s",
                item_id, len(data), (info or {}).get("lang", "?"))


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

    # 先标记为"提取中"，再创建 task
    # 必须在 create_task 之前 add，否则 task 还未执行时 warmup 轮询会看到 extracting=False
    # 而提前返回（asyncio.create_task 不会立即执行 task，要等当前协程 await 让出 CPU）
    _sub_extracting.add(item_id)
    asyncio.create_task(
        _extract_embedded_sub(item_id, cdn_url, user_agent, track_prefs),
        name=f"embedded_sub_{item_id}",
    )


def get_embedded_sub_status(item_id: str) -> dict:
    """返回内封字幕当前状态，供 Go 轮询等待。"""
    info = get_cached_embedded_sub_info(item_id)
    return {
        "cached": info is not None,
        "extracting": item_id in _sub_extracting,
        "lang": (info or {}).get("lang", ""),
        "title": (info or {}).get("title", ""),
        "codec": (info or {}).get("codec", "ass"),
    }


async def warmup_embedded_subtitle(
    item_id: str,
    cdn_url: str,
    user_agent: str = "",
    item_type: str = "",
    wait_timeout: float = 3.5,
) -> dict:
    """
    PlaybackInfo 阶段同步预热内封字幕：
    1. 先触发后台提取
    2. 若已有缓存则立即返回
    3. 否则在短时间内轮询等待提取结果
    """
    await trigger_embedded_sub_extraction(item_id, cdn_url, user_agent, item_type)

    deadline = time.monotonic() + max(wait_timeout, 0.1)
    while time.monotonic() < deadline:
        status = get_embedded_sub_status(item_id)
        if status["cached"]:
            return status
        if not status["extracting"]:
            return status
        await asyncio.sleep(0.25)

    return get_embedded_sub_status(item_id)



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
      1. httpx Range 请求下载 MKV 文件头（前 10MB）到本地临时文件
         → ffprobe 只读本地文件，完全绕开静态 OpenSSL 的 HTTPS SIGSEGV 问题
      2. ffprobe 探测本地文件的字幕轨道
      3. 按 track_prefs 匹配语言偏好
      4. ffmpeg 读远程 URL 提取字幕（ffmpeg 的 HTTPS 支持比 ffprobe 更稳定）
         若 ffmpeg 也 SIGSEGV，则回退为继续扩大 Range 下载完整文件再提取
      5. 缓存结果
    """
    # _sub_extracting.add 由调用方 trigger_embedded_sub_extraction 在 create_task 前完成，
    # 保证 warmup 轮询在 task 实际执行前就能看到 extracting=True
    t0 = time.monotonic()
    logger.info("[subtitle] 开始内封字幕提取: item_id=%s", item_id)

    try:
        import shutil, tempfile, os

        # ── Step0: 验证 ffprobe 二进制可用 ─────────────────────────────────
        ffprobe_path = shutil.which("ffprobe")
        ffmpeg_path  = shutil.which("ffmpeg")
        if not ffprobe_path or not ffmpeg_path:
            logger.warning("[subtitle] ffprobe/ffmpeg 未找到，内封字幕提取不可用")
            return

        # 先跑 -version 确认二进制本身能执行（防止 LFS 指针文件或架构不符）
        try:
            ver_proc = await asyncio.create_subprocess_exec(
                ffprobe_path, "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            ver_out, _ = await asyncio.wait_for(ver_proc.communicate(), timeout=10)
            ver_txt = ver_out.decode("utf-8", errors="replace").strip()
            if ver_proc.returncode != 0 or not ver_txt.startswith("ffprobe"):
                logger.error(
                    "[subtitle] ffprobe 二进制异常(rc=%s path=%s): %s",
                    ver_proc.returncode, ffprobe_path, ver_txt[:300],
                )
                return
            logger.info("[subtitle] ffprobe 版本: %s", ver_txt.splitlines()[0])
        except Exception as e:
            logger.error("[subtitle] ffprobe -version 执行失败: %s path=%s", e, ffprobe_path)
            return

        ua = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

        # ── Step1: Range 下载文件头 → 本地临时文件 ──────────────────────────
        # 静态 ffprobe 的 TLS 实现在某些宿主内核下访问 HTTPS 会 SIGSEGV。
        # 解决方案：Python (httpx) 负责 HTTPS，下载前 10MB 文件头到本地，
        # ffprobe 只读本地文件，完全绕开 TLS 问题。
        # MKV 的 Cues（索引）通常在文件头部或末尾，10MB 足以覆盖字幕轨道元数据。
        PROBE_SIZE = 10 * 1024 * 1024  # 10MB

        logger.debug("[subtitle] ffprobe 目标 URL: %s", cdn_url[:120] if cdn_url else "None")

        with tempfile.TemporaryDirectory(prefix="mmf_sub_") as tmpdir:
            head_path = os.path.join(tmpdir, "head.mkv")
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(
                        cdn_url,
                        headers={
                            "User-Agent": ua,
                            "Range": f"bytes=0-{PROBE_SIZE - 1}",
                        },
                        follow_redirects=True,
                    )
                    if resp.status_code not in (200, 206):
                        logger.warning(
                            "[subtitle] 下载文件头失败: status=%d item_id=%s",
                            resp.status_code, item_id,
                        )
                        _sub_probe_fail[item_id] = time.monotonic() + _SUB_PROBE_FAIL_TTL
                        return
                    with open(head_path, "wb") as f:
                        f.write(resp.content)
                logger.debug("[subtitle] 文件头已下载: %d bytes → %s", len(resp.content), head_path)
            except Exception as e:
                logger.warning("[subtitle] 下载文件头异常: %s item_id=%s", e, item_id)
                _sub_probe_fail[item_id] = time.monotonic() + _SUB_PROBE_FAIL_TTL
                return

            # ── Step2: ffprobe 探测本地文件头的字幕轨道 ──────────────────────
            probe_cmd = [
                "ffprobe", "-v", "warning",
                "-print_format", "json",
                "-show_streams", "-select_streams", "s",
                head_path,  # 本地文件，不走网络，完全绕开 TLS
            ]
            try:
                probe_proc = await asyncio.create_subprocess_exec(
                    *probe_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(probe_proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                logger.warning("[subtitle] ffprobe 超时: item_id=%s", item_id)
                _sub_probe_fail[item_id] = time.monotonic() + _SUB_PROBE_FAIL_TTL
                return
            except Exception as e:
                logger.warning("[subtitle] ffprobe 启动失败: %s item_id=%s", e, item_id)
                _sub_probe_fail[item_id] = time.monotonic() + _SUB_PROBE_FAIL_TTL
                return

            stderr_txt = stderr.decode("utf-8", errors="replace").strip()
            stdout_txt = stdout.decode("utf-8", errors="replace").strip()
            if stderr_txt:
                logger.info("[subtitle] ffprobe stderr(rc=%s): %s",
                            probe_proc.returncode, stderr_txt[:1000])

            if probe_proc.returncode != 0 or not stdout_txt:
                logger.warning(
                    "[subtitle] ffprobe 非正常退出: rc=%s stdout_empty=%s item_id=%s",
                    probe_proc.returncode, not stdout_txt, item_id,
                )
                _sub_probe_fail[item_id] = time.monotonic() + _SUB_PROBE_FAIL_TTL
                return

            try:
                probe_data = json.loads(stdout_txt)
            except Exception as e:
                logger.warning("[subtitle] ffprobe 输出解析失败: %s stdout=%r item_id=%s",
                               e, stdout_txt[:200], item_id)
                _sub_probe_fail[item_id] = time.monotonic() + _SUB_PROBE_FAIL_TTL
                return

            streams = probe_data.get("streams", [])
            if not streams:
                logger.info("[subtitle] 未发现内封字幕轨道: item_id=%s", item_id)
                _sub_no_track[item_id] = time.monotonic() + _SUB_NO_TRACK_TTL
                return

            # ── Step3: 过滤图形字幕，只保留文本字幕 ──────────────────────────
            BITMAP_CODECS = {"hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvbsub",
                             "dvb_subtitle", "xsub", "vobsub", "mov_text"}

            # 详细打印所有发现的字幕轨道
            logger.info("[subtitle] 发现 %d 条字幕轨道: item_id=%s", len(streams), item_id)
            for s in streams:
                s_lang  = (s.get("tags", {}).get("language") or "").strip()
                s_title = (s.get("tags", {}).get("title") or "").strip()
                s_codec = s.get("codec_name", "?")
                s_idx   = s.get("index", "?")
                is_bitmap = s_codec.lower() in BITMAP_CODECS
                logger.info(
                    "[subtitle]   轨道 index=%s codec=%s lang=%s title=%s %s",
                    s_idx, s_codec, s_lang or "(无)", s_title or "(无)",
                    "【图形字幕，跳过】" if is_bitmap else "【文本字幕，可提取】",
                )

            text_streams = [
                s for s in streams
                if s.get("codec_name", "").lower() not in BITMAP_CODECS
            ]
            if not text_streams:
                logger.info(
                    "[subtitle] 内封字幕均为图形格式，无法提取为ASS: item_id=%s",
                    item_id,
                )
                _sub_no_track[item_id] = time.monotonic() + _SUB_NO_TRACK_TTL
                return

            chosen_index: Optional[int] = None
            chosen_lang  = ""
            chosen_title = ""
            chosen_codec = ""
            if track_prefs:
                logger.info("[subtitle] 按偏好匹配轨道: prefs=%s", track_prefs)
                for pref in track_prefs:
                    pref_lower = pref.lower()
                    for s in text_streams:
                        lang  = (s.get("tags", {}).get("language") or "").lower()
                        title = (s.get("tags", {}).get("title") or "").lower()
                        if pref_lower in (lang, title) or pref_lower in lang or pref_lower in title:
                            chosen_index = s.get("index")
                            chosen_lang  = lang
                            chosen_title = (s.get("tags", {}).get("title") or "")
                            chosen_codec = s.get("codec_name", "ass")
                            logger.info("[subtitle] 偏好命中: pref=%s lang=%s title=%s", pref, lang, title)
                            break
                    if chosen_index is not None:
                        break

            if chosen_index is None:
                s0 = text_streams[0]
                chosen_index = s0.get("index")
                chosen_lang  = (s0.get("tags", {}).get("language") or "unknown")
                chosen_title = (s0.get("tags", {}).get("title") or "")
                chosen_codec = s0.get("codec_name", "ass")
                logger.info("[subtitle] 无偏好命中，取第一条文本字幕: lang=%s title=%s", chosen_lang, chosen_title)

            sub_stream_pos = next(
                (i for i, s in enumerate(streams) if s.get("index") == chosen_index), 0
            )
            logger.info(
                "[subtitle] 选择字幕轨道: item_id=%s stream_index=%s sub_pos=%d lang=%s title=%s codec=%s",
                item_id, chosen_index, sub_stream_pos, chosen_lang, chosen_title, chosen_codec,
            )

            # ── Step4: ffmpeg 从本地文件头提取 .ass ──────────────────────────
            # 用本地已下载的文件头，ffmpeg 不走网络，绕开静态 OpenSSL SIGSEGV
            out_path = os.path.join(tmpdir, "sub.ass")
            extract_cmd = [
                "ffmpeg", "-v", "warning",
                "-i", head_path,       # 本地文件，不走 HTTPS
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
                _, ext_stderr = await asyncio.wait_for(ext_proc.communicate(), timeout=60)
                if ext_proc.returncode != 0:
                    err_msg = ext_stderr.decode("utf-8", errors="replace").strip()
                    logger.warning(
                        "[subtitle] ffmpeg 提取失败(rc=%d): %s item_id=%s",
                        ext_proc.returncode, err_msg[-500:], item_id,
                    )
                    if "bitmap to bitmap" in err_msg or "Invalid argument" in err_msg:
                        _sub_no_track[item_id] = time.monotonic() + _SUB_NO_TRACK_TTL
                    else:
                        _sub_probe_fail[item_id] = time.monotonic() + _SUB_PROBE_FAIL_TTL
                    return
            except asyncio.TimeoutError:
                logger.warning("[subtitle] ffmpeg 提取超时(60s): item_id=%s", item_id)
                _sub_probe_fail[item_id] = time.monotonic() + _SUB_PROBE_FAIL_TTL
                return
            except Exception as e:
                logger.warning("[subtitle] ffmpeg 提取异常: %s item_id=%s", e, item_id)
                _sub_probe_fail[item_id] = time.monotonic() + _SUB_PROBE_FAIL_TTL
                return

            # 读取提取结果
            try:
                with open(out_path, "rb") as f:
                    sub_data = f.read()
            except Exception as e:
                logger.warning("[subtitle] 读取提取字幕失败: %s", e)
                return

        # tmpdir 自动清理，sub_data 已读出
        elapsed = time.monotonic() - t0
        logger.info(
            "[subtitle] 内封字幕提取完成: item_id=%s lang=%s size=%d bytes 耗时=%.1fs",
            item_id, chosen_lang, len(sub_data), elapsed,
        )

        # ── Step5: 尝试立即送 fontInAss 子集化，缓存处理后的结果 ────────────────
        sub_info = {"lang": chosen_lang, "title": chosen_title, "codec": chosen_codec}
        subsetted = await process_embedded_sub_with_font_in_ass(item_id, sub_data)
        if subsetted is not None:
            _set_cached_embedded_sub(item_id, subsetted, sub_info)
            logger.info(
                "[subtitle] 内封字幕已子集化并缓存: item_id=%s %d bytes → %d bytes",
                item_id, len(sub_data), len(subsetted),
            )
        else:
            # fontInAss 未启用或失败，缓存原始 ASS
            _set_cached_embedded_sub(item_id, sub_data, sub_info)

    except Exception as e:
        logger.error("[subtitle] 内封字幕提取异常: %s item_id=%s", e, item_id)
    finally:
        _sub_extracting.discard(item_id)