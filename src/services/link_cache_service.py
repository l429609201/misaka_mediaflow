# src/services/link_cache_service.py
# 302 直链缓存服务 — 支持 memory / database / redis / hybrid 后端
#
# 架构: Go 反代调 Python 内部 API → Python 查缓存 → 命中返回 / 未命中调 115 API → 写缓存
#
# 后端模式（环境变量 MISAKAMF_CACHE__BACKEND）：
#   memory   - 纯内存（重启丢失）
#   database - 内存 L1 + 数据库 L2（RedirectCache 表）
#   redis    - 内存 L1 + Redis L2
#   hybrid   - 内存 L1 + 数据库 L2（默认，等同 database）

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# 安全余量（秒）— 提前过期，避免拿到即将失效的链接
SAFETY_MARGIN = 60


# ═══════════════════════════════════════════════════════════════
# L1: 内存缓存
# ═══════════════════════════════════════════════════════════════

class _MemoryCache:
    """线程安全的内存缓存（带 TTL）"""

    def __init__(self, max_size: int = 10000, default_ttl: int = 600):
        self._data: dict[str, tuple[str, float]] = {}  # key → (url, expire_ts)
        self._lock = threading.Lock()
        self._max_size = max_size
        self._default_ttl = default_ttl

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            url, expire_ts = entry
            if time.time() >= expire_ts:
                del self._data[key]
                return None
            return url

    def set(self, key: str, url: str, ttl: int = 0):
        if ttl <= 0:
            ttl = self._default_ttl
        with self._lock:
            # 超限淘汰最旧 20%
            if len(self._data) >= self._max_size:
                to_remove = sorted(
                    self._data.items(), key=lambda x: x[1][1]
                )[:self._max_size // 5]
                for k, _ in to_remove:
                    del self._data[k]
            self._data[key] = (url, time.time() + ttl)

    def delete(self, key: str):
        with self._lock:
            self._data.pop(key, None)

    @property
    def size(self) -> int:
        return len(self._data)


# ═══════════════════════════════════════════════════════════════
# L2: 数据库缓存
# ═══════════════════════════════════════════════════════════════

async def _db_get(cache_key: str) -> Optional[tuple[str, int]]:
    """从数据库读取缓存，返回 (url, remaining_ttl) 或 None"""
    try:
        from sqlalchemy import select, delete as sa_delete
        from src.db import get_async_session_local
        from src.db.models.cache import RedirectCache
        from src.core.timezone import tm

        async with get_async_session_local() as db:
            result = await db.execute(
                select(RedirectCache).where(RedirectCache.cache_key == cache_key)
            )
            row = result.scalars().first()
            if not row:
                return None

            now_str = tm.now()
            if row.expires_at <= now_str:
                await db.execute(
                    sa_delete(RedirectCache).where(RedirectCache.cache_key == cache_key)
                )
                await db.commit()
                return None

            # 计算剩余 TTL
            try:
                expire_dt = datetime.fromisoformat(row.expires_at)
                now_dt = datetime.fromisoformat(now_str)
                remaining = max(int((expire_dt - now_dt).total_seconds()), 1)
            except Exception:
                remaining = 300

            # 命中计数
            row.hit_count = (row.hit_count or 0) + 1
            await db.commit()
            return (row.direct_url, remaining)
    except Exception as e:
        logger.warning("[缓存] DB 读取失败: %s", e)
        return None


async def _db_set(cache_key: str, url: str, ttl: int, item_id: str = "", storage_id: int = 0):
    """写入数据库缓存"""
    try:
        from sqlalchemy import select
        from src.db import get_async_session_local
        from src.db.models.cache import RedirectCache
        from src.core.timezone import tm

        now_str = tm.now()
        now_dt = datetime.fromisoformat(now_str)
        expire_dt = now_dt + timedelta(seconds=ttl)
        expires_at = expire_dt.isoformat()

        async with get_async_session_local() as db:
            result = await db.execute(
                select(RedirectCache).where(RedirectCache.cache_key == cache_key)
            )
            row = result.scalars().first()
            if row:
                row.direct_url = url
                row.expires_at = expires_at
                row.hit_count = 0
            else:
                row = RedirectCache(
                    cache_key=cache_key,
                    item_id=item_id or cache_key[:16],
                    storage_id=storage_id,
                    direct_url=url,
                    expires_at=expires_at,
                )
                db.add(row)
            await db.commit()
    except Exception as e:
        logger.warning("[缓存] DB 写入失败: %s", e)


async def _db_cleanup():
    """清理过期的数据库缓存"""
    try:
        from sqlalchemy import delete as sa_delete
        from src.db import get_async_session_local
        from src.db.models.cache import RedirectCache
        from src.core.timezone import tm

        now = tm.now()
        async with get_async_session_local() as db:
            result = await db.execute(
                sa_delete(RedirectCache).where(RedirectCache.expires_at <= now)
            )
            await db.commit()
            if result.rowcount > 0:
                logger.info("[缓存] 清理 %d 条 DB 过期记录", result.rowcount)
    except Exception as e:
        logger.warning("[缓存] DB 清理失败: %s", e)


# ═══════════════════════════════════════════════════════════════
# L2: Redis 缓存
# ═══════════════════════════════════════════════════════════════

_redis_client = None
_redis_key_prefix = "mmf:"


def _get_redis():
    """延迟初始化 Redis 客户端"""
    global _redis_client, _redis_key_prefix
    if _redis_client is not None:
        return _redis_client

    from src.core.config import settings
    cfg = settings.cache
    redis_url = cfg.redis_url
    _redis_key_prefix = cfg.key_prefix or "mmf:"

    # 兼容旧 redis 分字段配置
    if not redis_url:
        old = settings.redis
        if old.enabled and old.host:
            if old.password:
                redis_url = f"redis://:{old.password}@{old.host}:{old.port}/{old.db}"
            else:
                redis_url = f"redis://{old.host}:{old.port}/{old.db}"

    if not redis_url:
        logger.warning("[缓存] Redis URL 未配置，Redis 后端不可用")
        return None

    try:
        import redis as redis_lib
        _redis_client = redis_lib.Redis.from_url(
            redis_url,
            decode_responses=True,  # ★ 关键：返回 str 而非 bytes，避免弹幕库同款类型问题
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        _redis_client.ping()
        logger.info("[缓存] Redis 连接成功: %s", redis_url.split("@")[-1] if "@" in redis_url else redis_url)
        return _redis_client
    except Exception as e:
        logger.warning("[缓存] Redis 连接失败: %s", e)
        _redis_client = None
        return None


def _redis_get(cache_key: str) -> Optional[tuple[str, int]]:
    """从 Redis 读取缓存，返回 (url, remaining_ttl) 或 None"""
    client = _get_redis()
    if not client:
        return None
    try:
        full_key = _redis_key_prefix + cache_key
        raw = client.get(full_key)
        if raw is None:
            return None

        # ★ 类型安全：decode_responses=True 应返回 str，但做双重保险
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str):
            raw = str(raw)

        # 存储格式: JSON {"url": "..."}
        # 兼容：纯字符串 URL（旧格式）也能用
        if raw.startswith("{"):
            try:
                data = json.loads(raw)
                url = str(data.get("url", ""))
            except (json.JSONDecodeError, TypeError):
                url = raw
        else:
            url = raw

        if not url:
            return None
        ttl_remaining = client.ttl(full_key)
        if ttl_remaining is None or ttl_remaining < 0:
            ttl_remaining = 300
        return (url, int(ttl_remaining))
    except Exception as e:
        logger.warning("[缓存] Redis 读取失败: %s", e)
        return None


def _redis_set(cache_key: str, url: str, ttl: int):
    """写入 Redis 缓存"""
    client = _get_redis()
    if not client:
        return
    try:
        full_key = _redis_key_prefix + cache_key
        # JSON 格式存储，确保类型统一
        value = json.dumps({"url": url}, ensure_ascii=False)
        client.setex(full_key, ttl, value)
    except Exception as e:
        logger.warning("[缓存] Redis 写入失败: %s", e)


# ═══════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════

_memory_cache: Optional[_MemoryCache] = None


def _get_memory_cache() -> _MemoryCache:
    """延迟初始化内存缓存"""
    global _memory_cache
    if _memory_cache is None:
        from src.core.config import settings
        cfg = settings.cache
        _memory_cache = _MemoryCache(
            max_size=cfg.memory_maxsize,
            default_ttl=cfg.memory_default_ttl,
        )
    return _memory_cache


def _get_backend() -> str:
    """获取缓存后端类型"""
    from src.core.config import settings
    return settings.cache.backend.lower()


def _get_default_ttl() -> int:
    """获取默认 TTL"""
    from src.core.config import settings
    return settings.cache.memory_default_ttl


def make_cache_key(*parts: str) -> str:
    """用多个部分拼接后 SHA256 生成缓存键"""
    raw = ":".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()


def _calc_ttl(expires_in: int) -> int:
    """根据直链有效期计算实际缓存 TTL"""
    default_ttl = _get_default_ttl()
    if expires_in > SAFETY_MARGIN:
        return min(expires_in - SAFETY_MARGIN, default_ttl)
    return default_ttl


async def get_cached_url(cache_key: str) -> Optional[str]:
    """
    查询缓存，命中返回 URL，未命中返回 None

    查询顺序: L1 内存 → L2 (database 或 redis，取决于 backend 配置)
    """
    mem = _get_memory_cache()
    backend = _get_backend()

    # L1 内存
    url = mem.get(cache_key)
    if url:
        logger.debug("[缓存] L1 命中: %s...%s", cache_key[:8], cache_key[-4:])
        return url

    if backend == "memory":
        return None

    # L2 Redis
    if backend == "redis":
        result = _redis_get(cache_key)
        if result:
            url, remaining = result
            mem.set(cache_key, url, remaining)  # 回填 L1
            logger.debug("[缓存] Redis 命中: %s...%s", cache_key[:8], cache_key[-4:])
            return url
        return None

    # L2 Database (database / hybrid)
    result = await _db_get(cache_key)
    if result:
        url, remaining = result
        mem.set(cache_key, url, remaining)  # 回填 L1
        logger.debug("[缓存] DB 命中: %s...%s", cache_key[:8], cache_key[-4:])
        return url

    return None


async def set_cached_url(
    cache_key: str,
    url: str,
    expires_in: int = 0,
    item_id: str = "",
    storage_id: int = 0,
):
    """
    写入缓存

    写入范围: L1 内存 + L2 (database 或 redis，取决于 backend 配置)
    """
    ttl = _calc_ttl(expires_in)
    mem = _get_memory_cache()
    backend = _get_backend()

    # L1 内存（所有模式都写）
    mem.set(cache_key, url, ttl)

    if backend == "memory":
        pass
    elif backend == "redis":
        _redis_set(cache_key, url, ttl)
    else:
        # database / hybrid
        await _db_set(cache_key, url, ttl, item_id=item_id, storage_id=storage_id)

    logger.info("[缓存] 写入: key=%s...%s, ttl=%ds, backend=%s", cache_key[:8], cache_key[-4:], ttl, backend)


async def cleanup_expired():
    """清理过期缓存"""
    backend = _get_backend()
    if backend in ("database", "hybrid"):
        await _db_cleanup()


def get_cache_stats() -> dict:
    """缓存统计"""
    mem = _get_memory_cache()
    return {
        "backend": _get_backend(),
        "memory_size": mem.size,
        "default_ttl": _get_default_ttl(),
    }