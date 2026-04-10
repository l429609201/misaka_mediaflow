# app/api/v1/system.py
# 系统管理 API

import asyncio
import json as _json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func

from src.version import APP_NAME, VERSION, VERSION_TAG, BUILD_DATE, GIT_COMMIT
from src.core.security import verify_token
from src.core.config import settings
from src.core.timezone import tm
from src.db import get_async_session_local
from src.db.models import SystemConfig, OperationLog, MediaItem
from src.services.log_manager import (
    get_logs as _get_memory_logs,
    subscribe_to_logs, unsubscribe_from_logs,
    list_log_files as _list_log_files,
    read_log_file as _read_log_file,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["系统管理"])


class ConfigPayload(BaseModel):
    key: str
    value: str
    description: str = ""


# ==================== 健康检查 ====================

@router.get("/health")
async def health_check():
    """健康检查 — 返回 version.py 中的版本号"""
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": VERSION,
        "version_tag": VERSION_TAG,
        "build_date": BUILD_DATE,
        "git_commit": GIT_COMMIT,
        "timezone": tm.tz_offset_str,
        "time": tm.now(),
    }


# ==================== 仪表盘 ====================

@router.get("/dashboard", dependencies=[Depends(verify_token)])
async def get_dashboard():
    """全景仪表盘：活跃会话、资源统计、系统信息"""
    from src.services.media_server_service import media_server_service
    adapter = await media_server_service.get_adapter()

    # 基础统计
    from src.db.models import StrmFile
    async with get_async_session_local() as db:
        strm_count = (await db.execute(select(func.count()).select_from(StrmFile))).scalar() or 0

    result = {
        "strm_count": strm_count,
        "media_server_connected": adapter is not None,
    }

    if adapter:
        try:
            counts = await adapter.get_item_counts()
            result.update(counts)
        except Exception:
            pass
        try:
            sessions = await adapter.get_active_sessions()
            playing = [s for s in sessions if s.get("is_playing")]
            result["active_sessions"] = sessions
            result["playing_count"] = len(playing)
            result["session_count"] = len(sessions)
        except Exception:
            result["active_sessions"] = []
            result["playing_count"] = 0
            result["session_count"] = 0
        try:
            sys_info = await adapter.get_system_info()
            result["server_name"] = sys_info.get("ServerName", "")
            result["server_version"] = sys_info.get("Version", "")
            result["os"] = sys_info.get("OperatingSystemDisplayName", "")
        except Exception:
            pass
    else:
        result["movie_count"] = 0
        result["series_count"] = 0
        result["episode_count"] = 0
        result["playing_count"] = 0
        result["session_count"] = 0
        result["active_sessions"] = []

    return result


# ==================== 系统配置 ====================

@router.get("/config", dependencies=[Depends(verify_token)])
async def get_config():
    """获取所有系统配置"""
    async with get_async_session_local() as db:
        result = await db.execute(select(SystemConfig).order_by(SystemConfig.key))
        items = result.scalars().all()
        return {
            "items": [i.to_dict() for i in items],
            "total": len(items),
        }


@router.put("/config", dependencies=[Depends(verify_token)])
async def update_config(payload: ConfigPayload):
    """更新或创建系统配置"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == payload.key)
        )
        cfg = result.scalars().first()
        if cfg:
            cfg.value = payload.value
            if payload.description:
                cfg.description = payload.description
            cfg.updated_at = tm.now()
        else:
            cfg = SystemConfig(
                key=payload.key,
                value=payload.value,
                description=payload.description,
                updated_at=tm.now(),
            )
            db.add(cfg)
        await db.commit()
        return {"success": True, "key": payload.key}


@router.delete("/config/{key}", dependencies=[Depends(verify_token)])
async def delete_config(key: str):
    """删除系统配置"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        cfg = result.scalars().first()
        if not cfg:
            raise HTTPException(status_code=404, detail="config not found")
        await db.delete(cfg)
        await db.commit()
        return {"success": True}


# ==================== 302 反代配置（存数据库 systemconfig 表） ====================

# 反代配置的 key 和默认值
_PROXY_CONFIG_KEYS = {
    "go_port": 9906,
    "cache_ttl": 900,
    "mem_cache_size": 10000,
    "connect_timeout": 10,
    "ws_ping_interval": 30,
}


@router.get("/proxy-config", dependencies=[Depends(verify_token)])
async def get_proxy_config():
    """获取 302 反代配置（从数据库读取，未设置则用 config.yaml 的值作为初始值）"""
    import json as _json
    result = {}
    async with get_async_session_local() as db:
        for key, default_val in _PROXY_CONFIG_KEYS.items():
            db_key = f"proxy_{key}"
            row = await db.execute(
                select(SystemConfig).where(SystemConfig.key == db_key)
            )
            cfg = row.scalars().first()
            if cfg and cfg.value:
                try:
                    result[key] = _json.loads(cfg.value)
                except (ValueError, TypeError):
                    result[key] = cfg.value
            else:
                # 首次：从 config.yaml 取值写入数据库
                yaml_val = default_val
                if key == "go_port":
                    yaml_val = settings.server.go_port
                elif hasattr(settings.proxy, key):
                    yaml_val = getattr(settings.proxy, key)
                result[key] = yaml_val
                # 写入数据库持久化
                new_cfg = SystemConfig(
                    key=db_key,
                    value=_json.dumps(yaml_val),
                    description=f"302反代配置: {key}",
                    updated_at=tm.now(),
                )
                db.add(new_cfg)
        await db.commit()
    return result


class ProxyConfigPayload(BaseModel):
    go_port: int = None
    cache_ttl: int = None
    mem_cache_size: int = None
    connect_timeout: int = None
    ws_ping_interval: int = None


@router.post("/proxy-config", dependencies=[Depends(verify_token)])
async def update_proxy_config(payload: ProxyConfigPayload):
    """更新 302 反代配置（写入数据库 systemconfig 表）"""
    import json as _json
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    async with get_async_session_local() as db:
        for key, value in updates.items():
            db_key = f"proxy_{key}"
            row = await db.execute(
                select(SystemConfig).where(SystemConfig.key == db_key)
            )
            cfg = row.scalars().first()
            if cfg:
                cfg.value = _json.dumps(value)
                cfg.updated_at = tm.now()
            else:
                cfg = SystemConfig(
                    key=db_key,
                    value=_json.dumps(value),
                    description=f"302反代配置: {key}",
                    updated_at=tm.now(),
                )
                db.add(cfg)
        await db.commit()

    logger.info("302 反代配置已更新: %s", list(updates.keys()))
    return {"success": True, "updated": list(updates.keys())}


# ==================== IP 白名单（存数据库 systemconfig 表，key=ip_whitelist） ====================

@router.get("/ip-whitelist", dependencies=[Depends(verify_token)])
async def get_ip_whitelist():
    """获取 IP 白名单"""
    import json as _json
    async with get_async_session_local() as db:
        row = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "ip_whitelist")
        )
        cfg = row.scalars().first()
        if cfg and cfg.value:
            try:
                return {"items": _json.loads(cfg.value)}
            except (ValueError, TypeError):
                pass
    return {"items": []}


class IpWhitelistPayload(BaseModel):
    items: list[str]


@router.post("/ip-whitelist", dependencies=[Depends(verify_token)])
async def update_ip_whitelist(payload: IpWhitelistPayload):
    """更新 IP 白名单（整体覆盖写入）"""
    import json as _json
    from src.core.security import invalidate_whitelist_cache

    # 去空去重
    items = list(dict.fromkeys(s.strip() for s in payload.items if s.strip()))

    async with get_async_session_local() as db:
        row = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "ip_whitelist")
        )
        cfg = row.scalars().first()
        if cfg:
            cfg.value = _json.dumps(items)
            cfg.updated_at = tm.now()
        else:
            cfg = SystemConfig(
                key="ip_whitelist",
                value=_json.dumps(items),
                description="IP 白名单（白名单内免登录）",
                updated_at=tm.now(),
            )
            db.add(cfg)
        await db.commit()

    invalidate_whitelist_cache()
    logger.info("IP 白名单已更新: %s", items)
    return {"success": True, "items": items}


# ==================== 媒体库配置 ====================

from src.services.media_server_service import media_server_service as _ms_svc


@router.get("/media-server", dependencies=[Depends(verify_token)])
async def get_media_server():
    """获取媒体库配置（通过 media_server_service 统一读取）"""
    return await _ms_svc.get_config()


class MediaServerPayload(BaseModel):
    type: str = "emby"
    host: str
    api_key: str
    user_id: str = ""


@router.post("/media-server", dependencies=[Depends(verify_token)])
async def update_media_server(payload: MediaServerPayload):
    """保存媒体库配置（通过 media_server_service 统一写入）"""
    await _ms_svc.save_config(payload.model_dump())
    logger.info("媒体服务器配置已更新: host=%s user_id=%s", payload.host, payload.user_id)
    return {"success": True}


@router.post("/media-server/test", dependencies=[Depends(verify_token)])
async def test_media_server(payload: MediaServerPayload):
    """测试媒体库连接（使用传入参数，不影响已保存配置）"""
    host = payload.host.rstrip("/")
    try:
        adapter = await _ms_svc.get_adapter_with_params(
            host=host, api_key=payload.api_key, server_type=payload.type
        )
        libs = await adapter.get_libraries()
        lib_list = [
            {
                "id":   lib.get("ItemId", lib.get("Id", "")),
                "name": lib.get("Name", ""),
                "type": lib.get("CollectionType", "unknown"),
            }
            for lib in libs
        ]
        return {
            "success":   True,
            "libraries": lib_list,
            "message":   f"连接成功，找到 {len(lib_list)} 个媒体库",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


class MediaServerUsersPayload(BaseModel):
    host: str
    api_key: str
    type: str = "emby"


@router.post("/media-server/users", dependencies=[Depends(verify_token)])
async def get_media_server_users(payload: MediaServerUsersPayload):
    """用传入的 host+api_key 实时查询用户列表"""
    try:
        adapter = await _ms_svc.get_adapter_with_params(
            host=payload.host, api_key=payload.api_key, server_type=payload.type
        )
        users = await adapter.get_users()
        return {"success": True, "users": users}
    except Exception as e:
        return {"success": False, "users": [], "message": str(e)}


@router.get("/media-server/libraries", dependencies=[Depends(verify_token)])
async def get_media_libraries():
    """使用已保存的配置获取媒体库列表"""
    cfg = await _ms_svc.get_config()
    if not cfg.get("host") or not cfg.get("api_key"):
        return {"success": False, "message": "媒体服务器未配置", "libraries": []}
    try:
        libs = await _ms_svc.get_libraries()
        lib_list = [
            {
                "id":   lib.get("ItemId", lib.get("Id", "")),
                "name": lib.get("Name", ""),
                "type": lib.get("CollectionType", "unknown"),
            }
            for lib in libs
        ]
        return {"success": True, "libraries": lib_list}
    except Exception as e:
        return {"success": False, "message": str(e), "libraries": []}



class SelectedLibrariesPayload(BaseModel):
    library_ids: list[str]


@router.get("/media-server/selected-libraries", dependencies=[Depends(verify_token)])
async def get_selected_libraries():
    """获取用户选中的媒体库 ID 列表"""
    async with get_async_session_local() as db:
        row = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "selected_library_ids")
        )
        cfg = row.scalars().first()
        if cfg and cfg.value:
            try:
                return {"library_ids": _json.loads(cfg.value)}
            except (ValueError, TypeError):
                pass
    return {"library_ids": []}


@router.post("/media-server/selected-libraries", dependencies=[Depends(verify_token)])
async def save_selected_libraries(payload: SelectedLibrariesPayload):
    """保存用户选中的媒体库 ID 列表"""
    value = _json.dumps(payload.library_ids)
    async with get_async_session_local() as db:
        row = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "selected_library_ids")
        )
        cfg = row.scalars().first()
        if cfg:
            cfg.value = value
            cfg.updated_at = tm.now()
        else:
            db.add(SystemConfig(
                key="selected_library_ids", value=value,
                description="用户选中的媒体库 ID 列表", updated_at=tm.now(),
            ))
        await db.commit()
    return {"success": True}


# ==================== Go 反代进程管理 ====================

from src.services import go_proxy_service


@router.get("/go-proxy/status", dependencies=[Depends(verify_token)])
async def get_go_proxy_status():
    """获取 Go 反代进程状态"""
    return go_proxy_service.get_status()


@router.get("/go-proxy/status/stream")
async def go_proxy_status_stream(token: str = ""):
    """Go 反代状态 SSE 推送（仅在状态变化时发送事件）"""
    # SSE 通过 query param 传 token 认证
    if token:
        try:
            verify_token(token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")

    async def _event_generator():
        last_state = None
        while True:
            state = go_proxy_service.get_status()
            if state != last_state:
                last_state = state
                yield f"data: {_json.dumps(state)}\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/go-proxy/start", dependencies=[Depends(verify_token)])
async def start_go_proxy():
    """启动 Go 反代进程"""
    return await go_proxy_service.start()


@router.post("/go-proxy/stop", dependencies=[Depends(verify_token)])
async def stop_go_proxy():
    """停止 Go 反代进程"""
    return await go_proxy_service.stop()


# ==================== 本地目录浏览 ====================

import os
import platform


@router.get("/browse-local-dir", dependencies=[Depends(verify_token)])
async def browse_local_dir(path: str = ""):
    """浏览本地文件系统目录（仅返回子目录列表）"""
    # 默认起始路径：Linux / macOS 用 /，Windows 用盘符列表
    if not path:
        if platform.system() == "Windows":
            # Windows: 列出所有盘符
            import string
            drives = []
            for letter in string.ascii_uppercase:
                dp = f"{letter}:\\"
                if os.path.isdir(dp):
                    drives.append({"name": f"{letter}:", "path": dp, "is_dir": True})
            return {"path": "", "parent": "", "items": drives}
        else:
            path = "/"

    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return {"path": path, "parent": "", "items": [], "error": "目录不存在"}

    parent = os.path.dirname(path) if path != "/" else ""
    items = []
    try:
        for entry in sorted(os.scandir(path), key=lambda e: e.name.lower()):
            if entry.is_dir(follow_symlinks=False):
                try:
                    # 跳过无权限的目录
                    entry.stat()
                    items.append({
                        "name": entry.name,
                        "path": entry.path.replace("\\", "/"),
                        "is_dir": True,
                    })
                except PermissionError:
                    pass
    except PermissionError:
        return {"path": path, "parent": parent, "items": [], "error": "没有访问权限"}

    return {"path": path.replace("\\", "/"), "parent": parent.replace("\\", "/"), "items": items}


# ==================== Go 反代流量统计 ====================

@router.get("/go-proxy/traffic", dependencies=[Depends(verify_token)])
async def get_go_proxy_traffic():
    """获取 Go 反代流量统计（单次 REST，兼容保留）"""
    return go_proxy_service.get_traffic()


@router.get("/go-proxy/traffic/stream")
async def go_proxy_traffic_stream(token: str = ""):
    """Go 反代流量统计 SSE 推送（每 2 秒推送一次，替代前端轮询）"""
    # SSE 通过 query param 传 token 认证（与 status/stream 一致）
    if token:
        try:
            verify_token(token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")

    async def _event_generator():
        while True:
            try:
                data = go_proxy_service.get_traffic()
                yield f"data: {_json.dumps(data)}\n\n"
            except Exception:
                pass
            await asyncio.sleep(2)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== 操作日志 ====================

@router.get("/logs", dependencies=[Depends(verify_token)])
async def get_logs(module: str = "", page: int = 1, size: int = 50):
    """分页获取操作日志"""
    async with get_async_session_local() as db:
        query = select(OperationLog)
        count_query = select(func.count()).select_from(OperationLog)
        if module:
            query = query.where(OperationLog.module == module)
            count_query = count_query.where(OperationLog.module == module)

        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        result = await db.execute(
            query.order_by(OperationLog.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        items = result.scalars().all()
        return {
            "items": [i.to_dict() for i in items],
            "total": total,
            "page": page,
            "size": size,
        }


# ==================== SSE 实时日志流（对齐弹幕库） ====================

@router.get("/logs/stream")
async def stream_logs(request: Request):
    """SSE 实时日志推送（token 通过 query 参数传递）"""
    token = request.query_params.get("token", "")
    if token:
        from src.core.security import decode_jwt_token, get_api_token
        import hmac
        payload = decode_jwt_token(token)
        ok = (payload and payload.get("sub")) or hmac.compare_digest(token, get_api_token())
        if not ok:
            raise HTTPException(status_code=401, detail="Invalid token")
    else:
        from src.core.security import _check_ip_whitelist_async
        client_ip = request.client.host if request.client else ""
        if not await _check_ip_whitelist_async(client_ip):
            raise HTTPException(status_code=401, detail="Unauthorized")

    async def event_generator():
        q = asyncio.Queue(maxsize=200)
        subscribe_to_logs(q)
        try:
            # ★ 连接时先推送内存中已有的日志（对齐弹幕库）
            current_logs = _get_memory_logs()
            for log in reversed(current_logs):
                if '\n' in log:
                    lines = log.split('\n')
                    for line in lines:
                        yield f"data: {line}\n"
                    yield "\n"
                else:
                    yield f"data: {log}\n\n"
            # 持续推送新日志
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = q.get_nowait()
                    yield f"data: {line}\n\n"
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.3)
        finally:
            unsubscribe_from_logs(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ==================== 日志查询（对齐弹幕库） ====================

@router.get("/logs/memory", dependencies=[Depends(verify_token)])
async def get_memory_logs():
    """获取内存中最近的日志（最新 200 条）"""
    return _get_memory_logs()


@router.get("/logs/files", dependencies=[Depends(verify_token)])
async def get_log_files_list():
    """列出日志目录中的所有日志文件（包括轮转文件）"""
    return _list_log_files()


@router.get("/logs/files/{filename}", dependencies=[Depends(verify_token)])
async def get_log_file_content(filename: str, tail: int = 500):
    """读取指定日志文件的最后 N 行"""
    try:
        return _read_log_file(filename, tail=tail)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except IOError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 媒体库同步 ====================

@router.post("/sync-media-items", dependencies=[Depends(verify_token)])
async def sync_media_items(library_id: str = ""):
    """从 Emby/Jellyfin 同步媒体条目到 mediaitem 表（通过 media_server_service 获取适配器）"""
    adapter = await _ms_svc.get_adapter()
    if adapter is None:
        return {"success": False, "error": "媒体服务器未配置，请先在系统设置中配置媒体服务器", "synced": 0}

    try:
        # 获取媒体库
        if library_id:
            libraries = [{"ItemId": library_id}]
        else:
            libraries = await adapter.get_libraries()

        synced = 0
        async with get_async_session_local() as db:
            for lib in libraries:
                lib_id = lib.get("ItemId", lib.get("Id", ""))
                if not lib_id:
                    continue

                items = await adapter.get_items(lib_id)
                for item_data in items:
                    item_id = str(item_data.get("Id", ""))
                    if not item_id:
                        continue

                    # 检查是否已存在
                    result = await db.execute(
                        select(MediaItem).where(MediaItem.item_id == item_id)
                    )
                    existing = result.scalars().first()

                    # 提取字段
                    media_sources = item_data.get("MediaSources", [])
                    file_path = ""
                    file_size = 0
                    container = ""
                    media_source_id = ""
                    if media_sources:
                        ms = media_sources[0]
                        file_path = ms.get("Path", "")
                        file_size = ms.get("Size", 0)
                        container = ms.get("Container", "")
                        media_source_id = ms.get("Id", "")

                    provider_ids = item_data.get("ProviderIds", {})
                    tmdb_id = int(provider_ids.get("Tmdb", 0) or 0)
                    imdb_id = provider_ids.get("Imdb", "")

                    if existing:
                        existing.title = item_data.get("Name", existing.title)
                        existing.file_path = file_path or existing.file_path
                        existing.file_size = file_size or existing.file_size
                        existing.container = container or existing.container
                        existing.media_source_id = media_source_id or existing.media_source_id
                        existing.tmdb_id = tmdb_id or existing.tmdb_id
                        existing.imdb_id = imdb_id or existing.imdb_id
                        existing.synced_at = tm.now()
                    else:
                        media_item = MediaItem(
                            item_id=item_id,
                            title=item_data.get("Name", ""),
                            item_type=item_data.get("Type", ""),
                            year=item_data.get("ProductionYear", 0) or 0,
                            parent_id=str(item_data.get("ParentId", "")),
                            season_num=item_data.get("ParentIndexNumber", 0) or 0,
                            episode_num=item_data.get("IndexNumber", 0) or 0,
                            library_id=lib_id,
                            file_path=file_path,
                            file_size=file_size,
                            container=container,
                            media_source_id=media_source_id,
                            tmdb_id=tmdb_id,
                            imdb_id=imdb_id,
                            synced_at=tm.now(),
                        )
                        db.add(media_item)
                    synced += 1

            await db.commit()

        logger.info("媒体库同步完成: synced=%d", synced)
        return {"success": True, "synced": synced}

    except Exception as e:
        logger.error("媒体库同步失败: %s", e)
        return {"success": False, "error": str(e), "synced": 0}



# ==================== 通知渠道配置 ====================

class NotifyConfigPayload(BaseModel):
    telegram:   dict = {}
    serverchan: dict = {}
    webhook:    dict = {}


@router.get("/notify/config", dependencies=[Depends(verify_token)])
async def get_notify_config():
    """获取通知渠道配置"""
    from src.services import notify_service
    cfg = await notify_service._load_config()
    # 脱敏：token/key 返回时打码
    def _mask(s: str) -> str:
        return s[:4] + "****" + s[-4:] if s and len(s) > 8 else ("****" if s else "")
    safe = {}
    tg = cfg.get("telegram", {})
    safe["telegram"] = {**tg, "token": _mask(tg.get("token", ""))}
    sc = cfg.get("serverchan", {})
    safe["serverchan"] = {**sc, "key": _mask(sc.get("key", ""))}
    safe["webhook"] = cfg.get("webhook", {})
    return safe


@router.post("/notify/config", dependencies=[Depends(verify_token)])
async def save_notify_config(payload: NotifyConfigPayload):
    """保存通知渠道配置"""
    from src.services import notify_service
    # 如果传入的 token/key 是掩码（含****），则保留旧值
    old = await notify_service._load_config()

    def _merge_secret(new_val: str, old_val: str) -> str:
        return old_val if "****" in (new_val or "") else (new_val or "")

    cfg = payload.model_dump()
    if "token" in cfg.get("telegram", {}):
        cfg["telegram"]["token"] = _merge_secret(
            cfg["telegram"]["token"], old.get("telegram", {}).get("token", ""))
    if "key" in cfg.get("serverchan", {}):
        cfg["serverchan"]["key"] = _merge_secret(
            cfg["serverchan"]["key"], old.get("serverchan", {}).get("key", ""))

    ok = await notify_service.save_config(cfg)
    return {"success": ok}


@router.post("/notify/test", dependencies=[Depends(verify_token)])
async def test_notify():
    """发送测试通知"""
    from src.services.notify_service import send
    results = await send("Misaka MediaFlow 通知测试", "如果您收到此消息，说明通知渠道配置正确。")
    return {"success": bool(results), "results": results}



# ==================== TG Bot ====================

@router.get("/tg-bot/status", dependencies=[Depends(verify_token)])
async def tg_bot_status():
    """获取 TG Bot 运行状态"""
    from src.services.tg_bot_service import get_tg_bot
    bot = get_tg_bot()
    return {
        "running": bot._running if bot else False,
        "has_token": bool(bot._token) if bot else False,
        "chat_id": bot._chat_id if bot else "",
    }

@router.post("/tg-bot/restart", dependencies=[Depends(verify_token)])
async def tg_bot_restart():
    """重启 TG Bot（重新加载配置）"""
    from src.services.tg_bot_service import get_tg_bot, init_tg_bot, shutdown_tg_bot
    await shutdown_tg_bot()
    await init_tg_bot()
    bot = get_tg_bot()
    return {"success": True, "running": bot._running if bot else False}


# ═══════════════════════════════════════════════════════════════════════
#  增强功能 API
# ═══════════════════════════════════════════════════════════════════════

# ── 302 缓存 ──
@router.get("/302-cache/stats", dependencies=[Depends(verify_token)])
async def cache_302_stats():
    from src.services.p115.enhancements import cache_stats
    return cache_stats()

@router.post("/302-cache/clear", dependencies=[Depends(verify_token)])
async def cache_302_clear():
    from src.services.p115.enhancements import cache_clear
    return {"success": True, "cleared": cache_clear()}

# ── 生活事件守护 ──
@router.get("/life-guard/status", dependencies=[Depends(verify_token)])
async def life_guard_status():
    from src.services.p115.enhancements import get_guard_state
    return get_guard_state()

@router.post("/life-guard/tick", dependencies=[Depends(verify_token)])
async def life_guard_tick():
    from src.services.p115.enhancements import life_event_guard_tick
    return await life_event_guard_tick()

# ── 回收站清理 ──
@router.post("/recyclebin/clean", dependencies=[Depends(verify_token)])
async def recyclebin_clean():
    from src.services.p115.enhancements import clean_recyclebin
    return await clean_recyclebin()

# ── STRM 执行历史 ──
@router.get("/strm-history", dependencies=[Depends(verify_token)])
async def strm_exec_history(limit: int = 50):
    from src.services.p115.enhancements import get_strm_exec_history
    return {"history": get_strm_exec_history(limit)}

@router.post("/strm-history/clear", dependencies=[Depends(verify_token)])
async def strm_exec_history_clear():
    from src.services.p115.enhancements import clear_strm_exec_history
    return {"success": True, "cleared": clear_strm_exec_history()}

# ── 增强配置（最小文件大小 + 黑名单 + 增量cron + 回收站cron）──
class EnhancementConfigPayload(BaseModel):
    min_file_size_mb: float = 0
    strm_blacklist: list = []
    inc_sync_cron: str = ""
    recyclebin_cron: str = ""
    sync_del_enabled: bool = False
    life_guard_enabled: bool = False

@router.get("/enhancement-config", dependencies=[Depends(verify_token)])
async def get_enhancement_config():
    async with get_async_session_local() as db:
        row = await db.execute(select(SystemConfig).where(SystemConfig.key == "enhancement_config"))
        cfg = row.scalars().first()
        if cfg and cfg.value:
            return _json.loads(cfg.value)
    return {"min_file_size_mb": 0, "strm_blacklist": [], "inc_sync_cron": "",
            "recyclebin_cron": "", "sync_del_enabled": False, "life_guard_enabled": False}

@router.post("/enhancement-config", dependencies=[Depends(verify_token)])
async def save_enhancement_config(payload: EnhancementConfigPayload):
    async with get_async_session_local() as db:
        row = await db.execute(select(SystemConfig).where(SystemConfig.key == "enhancement_config"))
        obj = row.scalars().first()
        val = _json.dumps(payload.model_dump(), ensure_ascii=False)
        if obj:
            obj.value = val
        else:
            db.add(SystemConfig(key="enhancement_config", value=val))
        await db.commit()
    return {"success": True}
