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
            "embedded_sub_enabled",
            "embedded_sub_tracks",
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


# ── 公开接口：fontInAss 转发 ──────────────────────────────────────────────────

async def proxy_to_font_in_ass(
    original_path: str,
    query_string: str,
    request_headers: dict,
) -> Optional[tuple[int, bytes, dict]]:
    """
    将字幕请求转发给外置 fontInAss 服务。

    Args:
        original_path:   原始请求路径，如 /emby/videos/123/Subtitles/1/0/Stream.ass
        query_string:    原始 query string（含 api_key 等）
        request_headers: 原始请求头（透传 Cookie/Authorization）

    Returns:
        (status_code, body_bytes, response_headers)  或 None（未启用/失败）
    """
    cfg = await _load_config()
    if cfg.get("font_in_ass_enabled", "").lower() != "true":
        return None

    base_url = (cfg.get("font_in_ass_url") or "").rstrip("/")
    if not base_url:
        logger.warning("[subtitle] fontInAss 已启用但未配置地址")
        return None

    target = f"{base_url}{original_path}"
    if query_string:
        target = f"{target}?{query_string}"

    # 只透传必要头，避免 Host 冲突
    forward_headers = {}
    for h in ("authorization", "x-emby-token", "x-emby-authorization", "cookie"):
        v = request_headers.get(h) or request_headers.get(h.title())
        if v:
            forward_headers[h] = v

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(target, headers=forward_headers)
            resp_headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() in ("content-type", "content-encoding", "content-length")
            }
            logger.info(
                "[subtitle] fontInAss 转发成功: path=%s status=%d size=%d",
                original_path, resp.status_code, len(resp.content),
            )
            return resp.status_code, resp.content, resp_headers
    except Exception as e:
        logger.warning("[subtitle] fontInAss 转发失败: %s (url=%s)", e, target)
        return None


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
) -> None:
    """
    302 成功后异步触发内封字幕提取，不阻塞主流程。
    - 若开关未开启，直接返回
    - 若该 item_id 已有缓存或正在提取中，跳过
    """
    cfg = await _load_config()
    if cfg.get("embedded_sub_enabled", "").lower() != "true":
        return

    if item_id in _sub_extracting:
        logger.debug("[subtitle] 已在提取中，跳过: item_id=%s", item_id)
        return

    if get_cached_embedded_sub(item_id) is not None:
        logger.debug("[subtitle] 缓存已存在，跳过提取: item_id=%s", item_id)
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
            stdout, _ = await asyncio.wait_for(probe_proc.communicate(), timeout=30)
            probe_data = json.loads(stdout.decode("utf-8", errors="replace"))
        except asyncio.TimeoutError:
            logger.warning("[subtitle] ffprobe 超时: item_id=%s", item_id)
            return
        except Exception as e:
            logger.warning("[subtitle] ffprobe 失败: %s item_id=%s", e, item_id)
            return

        streams = probe_data.get("streams", [])
        if not streams:
            logger.info("[subtitle] 未发现内封字幕轨道: item_id=%s", item_id)
            return

        # ── Step2: 选择字幕轨道 ──────────────────────────────────────────────
        chosen_index: Optional[int] = None  # ffmpeg stream index (0:s:N)
        chosen_lang = ""

        if track_prefs:
            for pref in track_prefs:
                pref_lower = pref.lower()
                for s in streams:
                    lang = (s.get("tags", {}).get("language") or "").lower()
                    title = (s.get("tags", {}).get("title") or "").lower()
                    if pref_lower in (lang, title) or pref_lower in lang or pref_lower in title:
                        chosen_index = s.get("index")
                        chosen_lang = lang
                        break
                if chosen_index is not None:
                    break

        if chosen_index is None:
            # 无匹配偏好 → 取第一条字幕轨道
            s0 = streams[0]
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
        _set_cached_embedded_sub(item_id, sub_data)
        logger.info(
            "[subtitle] ✅ 内封字幕提取完成: item_id=%s lang=%s size=%d bytes 耗时=%.1fs",
            item_id, chosen_lang, len(sub_data), elapsed,
        )

    except Exception as e:
        logger.error("[subtitle] 内封字幕提取异常: %s item_id=%s", e, item_id)
    finally:
        _sub_extracting.discard(item_id)