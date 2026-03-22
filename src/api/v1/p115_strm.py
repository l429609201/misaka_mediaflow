# src/api/v1/p115_strm.py
# 115 STRM 同步 + 生活事件监控 + 整理分类 API

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional

from src.core.security import verify_token
from src.services.p115_strm_sync_service import P115StrmSyncService
from src.services.p115_life_monitor_service import get_life_monitor_service
from src.services.p115_organize_service import P115OrganizeService

router = APIRouter(prefix="/p115-strm", tags=["115 STRM 管理"])

_strm_sync_svc = P115StrmSyncService()
_organize_svc = P115OrganizeService()


# ─────────────────────── 请求体模型 ───────────────────────

class SyncPair(BaseModel):
    cloud_path: str   # 115 网盘路径（如 /媒体库）
    strm_path: str    # 本地 STRM 输出路径（如 /data/strm/媒体库）


class StrmSyncConfigPayload(BaseModel):
    sync_pairs: List[SyncPair] = []
    file_extensions: str = "mp4,mkv,avi,ts,iso,mov,m2ts"
    strm_link_host: str = ""
    clean_invalid: bool = True


class MonitorConfigPayload(BaseModel):
    enabled: bool = False
    poll_interval: int = 30
    monitor_paths: List[str] = []
    auto_inc_sync: bool = True


class OrganizeConfigPayload(BaseModel):
    source_paths: List[str] = []
    target_root: str = ""
    categories: list = []      # 新结构：列表，兼容旧 dict 格式（service 层自动迁移）
    dry_run: bool = False


# ─────────────────────── STRM 同步配置 ───────────────────────

@router.get("/sync/config", dependencies=[Depends(verify_token)])
async def get_sync_config():
    """获取 STRM 同步配置"""
    return await _strm_sync_svc.get_config()


@router.post("/sync/config", dependencies=[Depends(verify_token)])
async def save_sync_config(payload: StrmSyncConfigPayload):
    """保存 STRM 同步配置"""
    config = payload.model_dump()
    # 将 SyncPair 对象转为 dict
    config["sync_pairs"] = [p if isinstance(p, dict) else p for p in config["sync_pairs"]]
    await _strm_sync_svc.save_config(config)
    return {"success": True}


@router.get("/sync/status", dependencies=[Depends(verify_token)])
async def get_sync_status():
    """获取 STRM 同步状态"""
    return await _strm_sync_svc.get_status()


@router.post("/sync/full", dependencies=[Depends(verify_token)])
async def trigger_full_sync():
    """触发全量 STRM 生成"""
    return await _strm_sync_svc.trigger_full_sync()


@router.post("/sync/inc", dependencies=[Depends(verify_token)])
async def trigger_inc_sync():
    """触发增量 STRM 生成"""
    return await _strm_sync_svc.trigger_inc_sync()


# ─────────────────────── 生活事件监控 ───────────────────────

@router.get("/monitor/config", dependencies=[Depends(verify_token)])
async def get_monitor_config():
    """获取生活事件监控配置"""
    svc = get_life_monitor_service()
    return await svc.get_config()


@router.post("/monitor/config", dependencies=[Depends(verify_token)])
async def save_monitor_config(payload: MonitorConfigPayload):
    """保存生活事件监控配置"""
    svc = get_life_monitor_service()
    await svc.save_config(payload.model_dump())
    return {"success": True}


@router.get("/monitor/status", dependencies=[Depends(verify_token)])
async def get_monitor_status():
    """获取生活事件监控状态"""
    svc = get_life_monitor_service()
    return svc.get_status()


@router.post("/monitor/start", dependencies=[Depends(verify_token)])
async def start_monitor():
    """启动生活事件监控"""
    svc = get_life_monitor_service()
    return await svc.start()


@router.post("/monitor/stop", dependencies=[Depends(verify_token)])
async def stop_monitor():
    """停止生活事件监控"""
    svc = get_life_monitor_service()
    return await svc.stop()


# ─────────────────────── 整理分类 ───────────────────────

@router.get("/organize/config", dependencies=[Depends(verify_token)])
async def get_organize_config():
    """获取整理分类配置"""
    return await _organize_svc.get_config()


@router.post("/organize/config", dependencies=[Depends(verify_token)])
async def save_organize_config(payload: OrganizeConfigPayload):
    """保存整理分类配置"""
    await _organize_svc.save_config(payload.model_dump())
    return {"success": True}


@router.get("/organize/status", dependencies=[Depends(verify_token)])
async def get_organize_status():
    """获取整理分类状态"""
    return await _organize_svc.get_status()


@router.get("/organize/tmdb-status", dependencies=[Depends(verify_token)])
async def get_organize_tmdb_status():
    """检测 TMDB API Key 是否已配置（供前端显示规则有效性提示）"""
    try:
        import json
        from sqlalchemy import select
        from src.db import get_async_session_local
        from src.db.models.system import SystemConfig
        async with get_async_session_local() as db:
            row = await db.execute(
                select(SystemConfig).where(SystemConfig.key == "metadata_tmdb")
            )
            cfg = row.scalars().first()
            if cfg and cfg.value:
                data = json.loads(cfg.value)
                return {"available": bool(data.get("api_key", "").strip())}
    except Exception:
        pass
    return {"available": False}




