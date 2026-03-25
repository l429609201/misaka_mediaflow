# src/services/p115/modules/db_ops.py
# 数据库 ORM 操作模块
# 负责 P115FsCache / StrmFile / SystemConfig 的读写，
# 所有操作使用 async ORM（select + update/add + commit），无裸 SQL。

import json
import logging
from datetime import timedelta

from sqlalchemy import select

from src.db import get_async_session_local
from src.db.models.p115 import P115FsCache
from src.db.models.strm import StrmFile
from src.db.models.system import SystemConfig
from src.core.timezone import tm

logger = logging.getLogger(__name__)

# ── SystemConfig key 常量 ────────────────────────────────────────────────────
STRM_SYNC_CONFIG_KEY  = "p115_strm_sync_config"
STRM_SYNC_STATUS_KEY  = "p115_strm_sync_status"
MONITOR_CONFIG_KEY    = "p115_life_monitor_config"
P115_SETTINGS_KEY     = "p115_settings"


# ── STRM 同步配置 ─────────────────────────────────────────────────────────────

async def load_strm_config() -> dict:
    """读取 STRM 同步配置"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == STRM_SYNC_CONFIG_KEY)
        )
        cfg = result.scalars().first()
        if cfg and cfg.value:
            try:
                return json.loads(cfg.value)
            except Exception:
                pass
    return {}


async def save_strm_config(data: dict) -> None:
    """保存 STRM 同步配置"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == STRM_SYNC_CONFIG_KEY)
        )
        cfg = result.scalars().first()
        value = json.dumps(data, ensure_ascii=False)
        if cfg:
            cfg.value = value
            cfg.updated_at = tm.now()
        else:
            cfg = SystemConfig(
                key=STRM_SYNC_CONFIG_KEY, value=value,
                description="115 STRM 同步配置",
            )
            db.add(cfg)
        await db.commit()


# ── STRM 同步状态 ─────────────────────────────────────────────────────────────

async def load_strm_status() -> dict:
    """读取 STRM 同步状态"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == STRM_SYNC_STATUS_KEY)
        )
        cfg = result.scalars().first()
        if cfg and cfg.value:
            try:
                return json.loads(cfg.value)
            except Exception:
                pass
    return {}


async def save_strm_status(status: dict) -> None:
    """保存 STRM 同步状态"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == STRM_SYNC_STATUS_KEY)
        )
        cfg = result.scalars().first()
        value = json.dumps(status, ensure_ascii=False)
        if cfg:
            cfg.value = value
            cfg.updated_at = tm.now()
        else:
            cfg = SystemConfig(
                key=STRM_SYNC_STATUS_KEY, value=value,
                description="115 STRM 同步状态",
            )
            db.add(cfg)
        await db.commit()


# ── P115 高级设置 ─────────────────────────────────────────────────────────────

async def load_p115_settings() -> dict:
    """读取 115 高级设置（api_interval / api_concurrent 等）"""
    defaults = {"api_interval": 1.0, "api_concurrent": 3}
    try:
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == P115_SETTINGS_KEY)
            )
            cfg = result.scalars().first()
            if cfg and cfg.value:
                saved = json.loads(cfg.value)
                return {**defaults, **saved}
    except Exception as e:
        logger.debug("读取 115 高级设置失败: %s", e)
    return defaults


# ── 生活事件监控配置 ──────────────────────────────────────────────────────────

async def load_monitor_config() -> dict:
    """读取生活事件监控配置"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == MONITOR_CONFIG_KEY)
        )
        cfg = result.scalars().first()
        if cfg and cfg.value:
            try:
                return json.loads(cfg.value)
            except Exception:
                pass
    return {}


async def save_monitor_config(data: dict) -> None:
    """保存生活事件监控配置"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == MONITOR_CONFIG_KEY)
        )
        cfg = result.scalars().first()
        value = json.dumps(data, ensure_ascii=False)
        if cfg:
            cfg.value = value
            cfg.updated_at = tm.now()
        else:
            cfg = SystemConfig(
                key=MONITOR_CONFIG_KEY, value=value,
                description="115 生活事件监控配置",
            )
            db.add(cfg)
        await db.commit()


# ── P115FsCache + StrmFile 批量 ORM upsert ───────────────────────────────────

async def save_fscache_and_strmfile(
    fscache_batch: list[dict],
    strmfile_batch: list[dict],
    task_id: int = 0,
) -> dict:
    """
    批量 upsert P115FsCache（目录树缓存）和 StrmFile（STRM 文件记录）。
    使用 select + update/add 模式，与 p115_service._recursive_sync 保持一致。
    """
    fc_upserted = 0
    sf_upserted = 0

    # ── 写 P115FsCache ────────────────────────────────────────────────────────
    if fscache_batch:
        async with get_async_session_local() as db:
            for row in fscache_batch:
                file_id = row.get("file_id", "")
                if not file_id:
                    continue
                try:
                    result = await db.execute(
                        select(P115FsCache).where(P115FsCache.file_id == file_id)
                    )
                    existing = result.scalars().first()
                    if existing:
                        existing.parent_id  = row.get("parent_id",  existing.parent_id)
                        existing.name       = row.get("name",       existing.name)
                        existing.local_path = row.get("local_path", existing.local_path)
                        existing.sha1       = row.get("sha1",       existing.sha1)
                        existing.pick_code  = row.get("pick_code",  existing.pick_code)
                        existing.file_size  = row.get("file_size",  existing.file_size)
                        existing.is_dir     = row.get("is_dir",     existing.is_dir)
                        existing.mtime      = row.get("mtime",      existing.mtime)
                        existing.ctime      = row.get("ctime",      existing.ctime)
                        existing.updated_at = tm.now()
                    else:
                        db.add(P115FsCache(
                            file_id   = file_id,
                            parent_id = row.get("parent_id", ""),
                            name      = row.get("name",      ""),
                            local_path= row.get("local_path",""),
                            sha1      = row.get("sha1",      ""),
                            pick_code = row.get("pick_code", ""),
                            file_size = row.get("file_size", 0),
                            is_dir    = row.get("is_dir",    0),
                            mtime     = row.get("mtime",     ""),
                            ctime     = row.get("ctime",     ""),
                        ))
                    fc_upserted += 1
                except Exception as e:
                    logger.warning("【FsCache】写入失败 file_id=%s: %s", file_id, e)
            await db.commit()
        logger.info("【FsCache】目录树缓存写入完成: %d 条", fc_upserted)

    # ── 写 StrmFile ───────────────────────────────────────────────────────────
    if strmfile_batch:
        async with get_async_session_local() as db:
            for row in strmfile_batch:
                item_id = row.get("item_id", "")
                if not item_id:
                    continue
                try:
                    result = await db.execute(
                        select(StrmFile).where(StrmFile.item_id == item_id)
                    )
                    existing = result.scalars().first()
                    if existing:
                        existing.strm_path    = row.get("strm_path",    existing.strm_path)
                        existing.strm_content = row.get("strm_content", existing.strm_content)
                        existing.strm_mode    = row.get("strm_mode",    existing.strm_mode)
                        existing.file_size    = row.get("file_size",    existing.file_size)
                        existing.task_id      = task_id
                    else:
                        db.add(StrmFile(
                            task_id      = task_id,
                            item_id      = item_id,
                            strm_path    = row.get("strm_path",    ""),
                            strm_content = row.get("strm_content", ""),
                            strm_mode    = row.get("strm_mode",    "p115"),
                            file_size    = row.get("file_size",    0),
                        ))
                    sf_upserted += 1
                except Exception as e:
                    logger.warning("【StrmFile】写入失败 item_id=%s: %s", item_id, e)
            await db.commit()
        logger.info("【StrmFile】STRM文件记录写入完成: %d 条", sf_upserted)

    return {"fscache": fc_upserted, "strmfile": sf_upserted}


# ── P115FsCache 查询辅助 ──────────────────────────────────────────────────────

async def lookup_cid_by_path(local_path: str) -> str | None:
    """
    从 P115FsCache 按 local_path 查询目录 cid（is_dir=1）。
    用于 _resolve_cloud_cid 的本地缓存优先命中。
    """
    try:
        async with get_async_session_local() as db:
            result = await db.execute(
                select(P115FsCache.file_id).where(
                    P115FsCache.local_path == local_path,
                    P115FsCache.is_dir == 1,
                )
            )
            return result.scalar()
    except Exception as e:
        logger.debug("【FsCache】lookup_cid_by_path 失败: %s", e)
        return None


async def lookup_pickcode_by_path(local_path: str) -> str | None:
    """
    从 P115FsCache 按 local_path 查询文件 pick_code（is_dir=0）。
    用于播放时 FsCache 命中加速。
    """
    try:
        async with get_async_session_local() as db:
            result = await db.execute(
                select(P115FsCache.pick_code).where(
                    P115FsCache.local_path == local_path,
                    P115FsCache.is_dir == 0,
                )
            )
            return result.scalar()
    except Exception as e:
        logger.debug("【FsCache】lookup_pickcode_by_path 失败: %s", e)
        return None



async def load_fscache_tree(root_path: str, max_age_hours: float = 24.0) -> dict[str, list[dict]]:
    """
    预加载 P115FsCache 中以 root_path 为前缀的有效缓存记录，按 parent_id 分组返回。
    用于 iter_and_write_strm 中 iterdir 递归的缓存加速。

    参数：
      root_path     — 云盘路径前缀，如 /影音
      max_age_hours — 缓存最大有效时长（小时），默认 24h。
                      超过此时间的记录视为过期，不纳入缓存树，对应目录会重新调 API。
                      设为 0 则完全禁用缓存（始终返回空树）。

    返回：
      {parent_id: [{file_id, parent_id, name, local_path, sha1, pick_code, ...}, ...]}
      只包含 updated_at 在有效期内的记录；过期目录不在其中，_walk 会对其调 iterdir API。
    """
    if max_age_hours <= 0:
        logger.info("【FsCache】缓存已禁用(max_age_hours=0)，直接返回空树")
        return {}

    # 计算截止时间字符串（YYYY-MM-DD HH:MM:SS 字典序 = 时间序，可直接比较）
    cutoff_dt = tm.now_datetime() - timedelta(hours=max_age_hours)
    cutoff_str = tm.format(cutoff_dt)

    tree: dict[str, list[dict]] = {}
    total = 0
    expired = 0
    try:
        async with get_async_session_local() as db:
            result = await db.execute(
                select(P115FsCache).where(
                    P115FsCache.local_path.like(f"{root_path}%")
                )
            )
            rows = result.scalars().all()
            for row in rows:
                total += 1
                # 过期过滤：updated_at 为空或早于截止时间，跳过
                updated_at = row.updated_at or ""
                if updated_at < cutoff_str:
                    expired += 1
                    continue
                pid = str(row.parent_id)
                child = {
                    "file_id":    str(row.file_id),
                    "parent_id":  pid,
                    "name":       row.name or "",
                    "local_path": row.local_path or "",
                    "sha1":       row.sha1 or "",
                    "pick_code":  row.pick_code or "",
                    "file_size":  row.file_size or 0,
                    "is_dir":     int(row.is_dir or 0),
                    "mtime":      row.mtime or "",
                    "ctime":      row.ctime or "",
                }
                tree.setdefault(pid, []).append(child)
        fresh = total - expired
        logger.info(
            "【FsCache】预加载缓存树: root=%s TTL=%.0fh "
            "总记录=%d 有效=%d 已过期=%d 覆盖目录=%d",
            root_path, max_age_hours, total, fresh, expired, len(tree),
        )
    except Exception as e:
        logger.warning("【FsCache】预加载缓存树失败: %s", e)
    return tree