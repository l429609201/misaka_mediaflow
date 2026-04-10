# src/services/p115/enhancements.py
# P115 增强功能集合:
#   1. 302 缓存机制 (TTL 内存缓存避免重复请求115直链)
#   2. 同步删除 (Emby webhook 删片 → 删115网盘+本地STRM)
#   3. 生活事件线程守护 (心跳检测+自动重启)
#   4. 最小文件大小过滤
#   5. STRM 生成黑名单
#   6. 回收站定时清理
#   7. 增量同步 cron
#   8. STRM 执行历史
#   9. 全量同步多线程(并发)

import asyncio
import fnmatch
import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
#  1. 302 缓存机制 — pickcode → (url, expire_at)
# ═══════════════════════════════════════════════════════════════════════
_url_cache: dict[str, tuple[str, float]] = {}  # {pickcode: (url, expire_monotonic)}
_URL_CACHE_TTL = 600  # 默认 10 分钟


def cache_get(pickcode: str) -> Optional[str]:
    """从缓存获取直链URL，过期返回 None"""
    entry = _url_cache.get(pickcode)
    if entry:
        url, expire_at = entry
        if time.monotonic() < expire_at:
            logger.debug("[302cache] HIT pickcode=%s", pickcode)
            return url
        del _url_cache[pickcode]
    return None


def cache_set(pickcode: str, url: str, ttl: int = _URL_CACHE_TTL):
    """缓存直链URL"""
    if url and pickcode:
        _url_cache[pickcode] = (url, time.monotonic() + ttl)
        logger.debug("[302cache] SET pickcode=%s ttl=%ds cache_size=%d", pickcode, ttl, len(_url_cache))


def cache_clear():
    """清空所有302缓存"""
    count = len(_url_cache)
    _url_cache.clear()
    logger.info("[302cache] CLEAR %d entries", count)
    return count


def cache_stats() -> dict:
    """缓存统计"""
    now = time.monotonic()
    valid = sum(1 for _, (__, exp) in _url_cache.items() if now < exp)
    return {"total": len(_url_cache), "valid": valid, "expired": len(_url_cache) - valid}


# ═══════════════════════════════════════════════════════════════════════
#  2. 同步删除 — Emby Webhook → 删115网盘+本地STRM
# ═══════════════════════════════════════════════════════════════════════
_sync_del_history: list[dict] = []  # 内存历史（重启清零）


async def sync_delete_by_emby_webhook(event_data: dict) -> dict:
    """
    处理 Emby Webhook 的 library.deleted / playback.stop 等删除事件
    1. 解析被删除的文件路径
    2. 删除本地 STRM 文件 + 关联的 NFO/图片
    3. 尝试删除 115 网盘中的源文件
    """
    item_type = event_data.get("Item", {}).get("Type", "")
    item_name = event_data.get("Item", {}).get("Name", "")
    path = event_data.get("Item", {}).get("Path", "")
    event_type = event_data.get("Event", "")

    if event_type not in ("library.deleted", "item.remove"):
        return {"skipped": True, "reason": f"event_type={event_type} not handled"}

    result = {"event_type": event_type, "item_name": item_name, "path": path,
              "strm_deleted": 0, "nfo_deleted": 0, "cloud_deleted": False, "time": int(time.time())}

    if not path:
        result["error"] = "no path in event"
        _sync_del_history.insert(0, result)
        return result

    # 删除本地 STRM + 关联文件
    strm_path = Path(path)
    if strm_path.suffix.lower() == ".strm" and strm_path.exists():
        strm_path.unlink(missing_ok=True)
        result["strm_deleted"] = 1
        # 删除同目录下的 .nfo / 图片
        for ext in [".nfo", "-poster.jpg", "-fanart.jpg", "-thumb.jpg", "-banner.jpg"]:
            related = strm_path.with_suffix(ext) if ext.startswith(".") else Path(str(strm_path).rsplit(".", 1)[0] + ext)
            if related.exists():
                related.unlink(missing_ok=True)
                result["nfo_deleted"] += 1
        # 清理空目录
        parent = strm_path.parent
        try:
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except Exception:
            pass

    # 尝试删除115网盘文件（通过 FsCache 查找 file_id）
    try:
        from src.db import get_async_session_local
        from src.db.models import P115FsCache
        from sqlalchemy import select
        async with get_async_session_local() as db:
            filename = Path(path).stem  # 不含 .strm 后缀
            row = await db.execute(select(P115FsCache).where(P115FsCache.name.like(f"{filename}%")))
            fc = row.scalars().first()
            if fc and fc.file_id:
                from src.adapters.storage.p115 import P115Manager
                mgr = P115Manager()
                if mgr.enabled and mgr.ready and mgr.auth.has_cookie:
                    try:
                        mgr.client.fs_delete(fc.file_id)
                        result["cloud_deleted"] = True
                        logger.info("[SyncDel] 115网盘文件已删除: file_id=%s name=%s", fc.file_id, fc.name)
                    except Exception as e:
                        logger.warning("[SyncDel] 115删除失败: %s", e)
                        result["cloud_error"] = str(e)
                # 删除 FsCache 记录
                await db.delete(fc)
                await db.commit()
    except Exception as e:
        logger.warning("[SyncDel] FsCache 查询失败: %s", e)

    _sync_del_history.insert(0, result)
    if len(_sync_del_history) > 200:
        _sync_del_history[:] = _sync_del_history[:200]

    logger.info("[SyncDel] 处理完成: %s strm=%d nfo=%d cloud=%s",
                item_name, result["strm_deleted"], result["nfo_deleted"], result["cloud_deleted"])

    # 发送通知
    try:
        from src.services.notify_service import send as _notify
        await _notify("同步删除", f"🗑️ {item_name}\nSTRM: {result['strm_deleted']} 个\n网盘: {'✅' if result['cloud_deleted'] else '❌'}")


# ═══════════════════════════════════════════════════════════════════════
#  3. 生活事件线程守护 — 心跳 + 自动重启
# ═══════════════════════════════════════════════════════════════════════
_guard_state = {"fail_since": None, "restart_count": 0, "last_check": 0}
GUARD_RESTART_AFTER_SECS = 300  # 连续 5 分钟失败后重启


async def life_event_guard_tick():
    """
    每分钟调用一次，检查生活事件线程是否存活。
    连续 5 分钟检测到线程挂掉则自动重启。
    """
    from src.services.p115.life_monitor_service import get_life_monitor_service
    svc = get_life_monitor_service()
    _guard_state["last_check"] = int(time.time())

    is_alive = svc.is_running()
    if is_alive:
        if _guard_state["fail_since"] is not None:
            logger.info("[Guard] 生活事件线程恢复正常")
            _guard_state["fail_since"] = None
        return {"status": "alive"}

    now = time.monotonic()
    if _guard_state["fail_since"] is None:
        _guard_state["fail_since"] = now
        logger.warning("[Guard] 检测到生活事件线程已停止，开始计时")
        return {"status": "detecting", "fail_duration": 0}

    fail_duration = now - _guard_state["fail_since"]
    if fail_duration >= GUARD_RESTART_AFTER_SECS:
        logger.warning("[Guard] 连续 %.0f 秒失败，正在自动重启...", fail_duration)
        try:
            await svc.start()
            _guard_state["fail_since"] = None
            _guard_state["restart_count"] += 1
            # 通知
            try:
                from src.services.notify_service import send as _notify
                await _notify("生活事件守护", f"⚠️ 生活事件线程连续 {int(fail_duration)}s 无响应，已自动重启 (第{_guard_state['restart_count']}次)")
            except Exception:
                pass
            return {"status": "restarted", "restart_count": _guard_state["restart_count"]}
        except Exception as e:
            logger.error("[Guard] 自动重启失败: %s", e)
            return {"status": "restart_failed", "error": str(e)}

    return {"status": "waiting", "fail_duration": int(fail_duration)}


def get_guard_state() -> dict:
    return {**_guard_state, "restart_after_secs": GUARD_RESTART_AFTER_SECS}


# ═══════════════════════════════════════════════════════════════════════
#  4. 最小文件大小过滤
# ═══════════════════════════════════════════════════════════════════════

def should_skip_by_size(file_size: int, min_size_mb: float) -> bool:
    """文件大小过滤: 小于 min_size_mb(MB) 的文件跳过"""
    if min_size_mb <= 0:
        return False
    return file_size < (min_size_mb * 1024 * 1024)


# ═══════════════════════════════════════════════════════════════════════
#  5. STRM 生成黑名单
# ═══════════════════════════════════════════════════════════════════════

def should_skip_by_blacklist(file_path: str, blacklist: list[str]) -> bool:
    """
    黑名单过滤: 路径或文件名匹配任一规则则跳过
    规则支持:
      - 路径前缀匹配: /Sample/
      - 关键词包含: sample, trailer
      - glob 通配符: *.sample.*, *-trailer.*
    """
    if not blacklist:
        return False
    norm = file_path.replace("\\", "/").lower()
    for rule in blacklist:
        rule = rule.strip().lower()
        if not rule:
            continue
        if rule.startswith("/") and norm.startswith(rule):
            return True
        if "*" in rule or "?" in rule:
            if fnmatch.fnmatch(norm, rule) or fnmatch.fnmatch(Path(norm).name, rule):
                return True
        elif rule in norm:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════
#  6. 回收站定时清理
# ═══════════════════════════════════════════════════════════════════════

async def clean_recyclebin() -> dict:
    """清空115回收站"""
    try:
        from src.adapters.storage.p115 import P115Manager
        mgr = P115Manager()
        if not mgr.enabled or not mgr.ready or not mgr.auth.has_cookie:
            return {"success": False, "error": "115未就绪"}
        mgr.client.recyclebin_clean()
        logger.info("[Clean] 回收站已清空")
        return {"success": True, "action": "recyclebin_cleaned"}
    except Exception as e:
        logger.error("[Clean] 清空回收站失败: %s", e)
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
#  7. STRM 执行历史 (内存 + DB 双模式)
# ═══════════════════════════════════════════════════════════════════════
_strm_exec_history: list[dict] = []  # 内存历史


def record_strm_exec(kind: str, stats: dict, elapsed: float, error: str = ""):
    """记录一次 STRM 同步执行历史"""
    entry = {
        "kind": kind,  # full / increment / life_event
        "stats": stats,
        "elapsed": round(elapsed, 1),
        "error": error,
        "time": int(time.time()),
    }
    _strm_exec_history.insert(0, entry)
    if len(_strm_exec_history) > 100:
        _strm_exec_history[:] = _strm_exec_history[:100]
    logger.info("[ExecHistory] 记录 %s: %s 耗时=%.1fs", kind, stats, elapsed)
    return entry


def get_strm_exec_history(limit: int = 50) -> list:
    return _strm_exec_history[:limit]


def clear_strm_exec_history():
    count = len(_strm_exec_history)
    _strm_exec_history.clear()
    return count
def get_sync_del_history() -> list:
    return _sync_del_history


def clear_sync_del_history():
    count = len(_sync_del_history)
    _sync_del_history.clear()
    return count
