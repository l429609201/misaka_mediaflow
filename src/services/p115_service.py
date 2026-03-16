# app/services/p115_service.py
# 115 网盘业务逻辑

import logging

from sqlalchemy import select, func

from src.db import get_async_session_local
from src.db.models import P115FsCache, P115OrganizeRecord
from src.core.timezone import tm

logger = logging.getLogger(__name__)


def _get_manager():
    """延迟导入避免循环依赖"""
    from src.adapters.storage.p115 import P115Manager
    return P115Manager()


class P115Service:
    """115 网盘业务逻辑"""

    async def _load_cookie_from_db(self, manager) -> None:
        """
        从数据库 systemconfig 表加载持久化的 Cookie。
        解决 BUG：P115Manager.initialize() 只从 config.yaml 读取 cookie，
        但用户通过网页设置/扫码获得的 CK 保存在数据库中，
        导致每次重启后 CK 丢失、前端永远显示"未配置"。
        """
        if manager.auth.has_cookie:
            return  # config.yaml 已有 cookie，无需从 DB 加载
        try:
            from src.db.models.system import SystemConfig
            async with get_async_session_local() as db:
                result = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == "p115_cookie")
                )
                cfg = result.scalars().first()
                if cfg and cfg.value:
                    manager.auth.set_cookie(cfg.value)
                    logger.info("从数据库加载 115 Cookie 成功 (len=%d)", len(cfg.value))
        except Exception as e:
            logger.warning("从数据库加载 115 Cookie 失败: %s", e)

    async def get_status(self) -> dict:
        """获取 115 模块状态"""
        manager = _get_manager()
        if not manager.enabled:
            return {"enabled": False, "cookie": False, "openapi": False}
        # 自动初始化
        if not manager.ready:
            manager.initialize()
        # 从数据库加载持久化 Cookie（解决 config.yaml 未配置但数据库已有的场景）
        await self._load_cookie_from_db(manager)
        return {
            "enabled": True,
            "cookie": manager.auth.has_cookie if manager.ready else False,
            "openapi": manager.auth.has_openapi if manager.ready else False,
            "rate_blocked": manager.rate_limiter.is_blocked if manager.ready else False,
            "cache_size": manager.id_path_cache.size if manager.ready else 0,
        }

    async def get_account_info(self) -> dict:
        """获取 115 账号信息（用户名、头像、存储空间）"""
        manager = _get_manager()
        if not manager.enabled or not manager.ready:
            return {"logged_in": False}
        await self._load_cookie_from_db(manager)
        if not manager.auth.has_cookie:
            return {"logged_in": False}
        try:
            user = await manager.adapter.get_user_info()
            space = await manager.adapter.get_space_usage()
            if not user.get("user_name"):
                return {"logged_in": False}
            return {
                "logged_in": True,
                "user_name": user.get("user_name", ""),
                "avatar": user.get("face", ""),
                "user_id": user.get("user_id", ""),
                "vip": user.get("vip", 0),
                "vip_name": user.get("vip_name", ""),
                "vip_color": user.get("vip_color", ""),
                "space_total": space.get("total", 0),
                "space_used": space.get("used", 0),
                "space_free": space.get("free", 0),
            }
        except Exception as e:
            logger.error("获取 115 账号信息失败: %s", e)
            return {"logged_in": False}

    async def set_cookie(self, cookie: str) -> dict:
        """设置 115 Cookie"""
        manager = _get_manager()
        if not manager.ready:
            manager.initialize()
        manager.auth.set_cookie(cookie)
        # 验证
        valid = await manager.auth.verify_cookie()
        # 持久化到 systemconfig
        async with get_async_session_local() as db:
            from src.db.models import SystemConfig
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == "p115_cookie")
            )
            cfg = result.scalars().first()
            if cfg:
                cfg.value = cookie
                cfg.updated_at = tm.now()
            else:
                cfg = SystemConfig(key="p115_cookie", value=cookie, description="115 Cookie")
                db.add(cfg)
            await db.commit()
        return {"success": True, "valid": valid}

    async def qrcode_step1(self, app: str = "web") -> dict:
        """扫码登录第1步 — 获取二维码"""
        manager = _get_manager()
        if not manager.ready:
            manager.initialize()
        result = await manager.auth.qrcode_login_step1(app=app)
        if result:
            return {"success": True, **result}
        return {"success": False, "error": "获取二维码失败"}

    async def qrcode_step2(self, uid: str, time_val: str, sign: str, app: str = "web") -> dict:
        """扫码登录第2步 — 轮询状态（支持多种状态码）"""
        manager = _get_manager()
        if not manager.ready:
            manager.initialize()
        result = await manager.auth.qrcode_login_step2(uid, time_val, sign, app=app)
        # result: {status: "waiting"|"scanned"|"success"|"expired"|"canceled"|"error", cookie?}
        if result.get("status") == "success" and result.get("cookie"):
            # 写入数据库持久化
            from src.db import get_async_session_local
            from sqlalchemy import select
            from src.db.models.system import SystemConfig
            async with get_async_session_local() as db:
                stmt = select(SystemConfig).where(SystemConfig.key == "p115_cookie")
                cfg = (await db.execute(stmt)).scalar_one_or_none()
                if cfg:
                    cfg.value = result["cookie"]
                else:
                    cfg = SystemConfig(key="p115_cookie", value=result["cookie"], description="115 Cookie")
                    db.add(cfg)
                await db.commit()
            return {"success": True, **result}
        return {"success": False, **result}

    async def sync_directory(self, cid: str = "0", path: str = "/") -> dict:
        """同步 115 目录树到 p115fscache"""
        manager = _get_manager()
        if not manager.enabled:
            return {"error": "115 not enabled", "synced": 0}

        logger.info("同步 115 目录树: cid=%s, path=%s", cid, path)
        synced = await self._recursive_sync(manager, cid, path, depth=0)
        return {"synced": synced, "cid": cid}

    async def _recursive_sync(self, manager, cid: str, path: str, depth: int) -> int:
        """递归同步目录"""
        if depth > 20:
            return 0

        entries = await manager.adapter.list_files("", cid=cid)
        synced = 0

        async with get_async_session_local() as db:
            for entry in entries:
                full_path = f"{path}/{entry.name}".replace("//", "/")
                # 更新或插入缓存
                result = await db.execute(
                    select(P115FsCache).where(
                        P115FsCache.file_id == entry.file_id
                    )
                )
                existing = result.scalars().first()
                if existing:
                    existing.name = entry.name
                    existing.local_path = full_path
                    existing.sha1 = entry.sha1
                    existing.pick_code = entry.pick_code
                    existing.ed2k = entry.ed2k
                    existing.file_size = entry.size
                    existing.is_dir = 1 if entry.is_dir else 0
                    existing.mtime = entry.mtime
                    existing.ctime = entry.ctime
                    existing.updated_at = tm.now()
                else:
                    cache_entry = P115FsCache(
                        file_id=entry.file_id,
                        parent_id=cid,
                        name=entry.name,
                        local_path=full_path,
                        sha1=entry.sha1,
                        pick_code=entry.pick_code,
                        ed2k=entry.ed2k,
                        file_size=entry.size,
                        is_dir=1 if entry.is_dir else 0,
                        mtime=entry.mtime,
                        ctime=entry.ctime,
                    )
                    db.add(cache_entry)
                synced += 1
            await db.commit()

        # 递归子目录
        for entry in entries:
            if entry.is_dir:
                full_path = f"{path}/{entry.name}".replace("//", "/")
                synced += await self._recursive_sync(manager, entry.file_id, full_path, depth + 1)

        return synced

    async def get_download_url(self, pick_code: str) -> dict:
        """获取 115 直链"""
        manager = _get_manager()
        if not manager.enabled:
            return {"url": "", "expires_in": 0, "error": "115 not enabled"}
        link = await manager.adapter.get_download_url(pick_code)
        if link.url:
            return {"url": link.url, "expires_in": link.expires_in}
        return {"url": "", "expires_in": 0, "error": "link failed"}

    async def browse_files(self, cid: str = "0", page: int = 1, size: int = 50) -> dict:
        """从 p115fscache 浏览目录"""
        async with get_async_session_local() as db:
            count_result = await db.execute(
                select(func.count()).select_from(P115FsCache)
                .where(P115FsCache.parent_id == cid)
            )
            total = count_result.scalar() or 0

            result = await db.execute(
                select(P115FsCache)
                .where(P115FsCache.parent_id == cid)
                .order_by(P115FsCache.is_dir.desc(), P115FsCache.name)
                .offset((page - 1) * size)
                .limit(size)
            )
            items = result.scalars().all()
            return {
                "items": [i.to_dict() for i in items],
                "total": total,
                "cid": cid,
                "page": page,
                "size": size,
            }

    async def organize_files(self, file_ids: list[str]) -> dict:
        """115 文件整理（记录到 p115organizerecord）"""
        manager = _get_manager()
        if not manager.enabled:
            return {"processed": 0, "error": "115 not enabled"}

        processed = 0
        async with get_async_session_local() as db:
            for fid in file_ids:
                # 查询文件信息
                result = await db.execute(
                    select(P115FsCache).where(P115FsCache.file_id == fid)
                )
                cache_entry = result.scalars().first()
                if not cache_entry:
                    continue

                # 检查是否已处理
                result = await db.execute(
                    select(P115OrganizeRecord).where(P115OrganizeRecord.file_id == fid)
                )
                if result.scalars().first():
                    continue

                record = P115OrganizeRecord(
                    file_id=fid,
                    pick_code=cache_entry.pick_code,
                    original_name=cache_entry.name,
                    status="pending",
                )
                db.add(record)
                processed += 1

            await db.commit()

        logger.info("115 文件整理记录已创建: %d 条", processed)
        return {"processed": processed}



    async def browse_dir_tree(self, cid: str = "0") -> dict:
        """浏览 115 目录树 — 只返回文件夹，用于路径选择器
        直接调用 115 API 实时获取，不依赖缓存"""
        manager = _get_manager()
        if not manager.enabled:
            return {"items": [], "cid": cid, "error": "115 not enabled"}

        if not manager.ready:
            manager.initialize()

        await self._load_cookie_from_db(manager)

        try:
            entries = await manager.adapter.list_files("", cid=cid)
            dirs = []
            for entry in entries:
                if entry.is_dir:
                    dirs.append({
                        "file_id": entry.file_id,
                        "name": entry.name,
                        "is_dir": True,
                    })
            dirs.sort(key=lambda d: d["name"])
            return {"items": dirs, "cid": cid}
        except Exception as e:
            logger.error("浏览 115 目录树失败: %s", e)
            return {"items": [], "cid": cid, "error": str(e)}
