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


class OrganizeRunPayload(BaseModel):
    """触发整理任务时，可选传入待整理目录列表（覆盖 path_mapping 中的配置）"""
    source_paths: List[str] = []


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


# ─────────────────────── 整理分类触发 ───────────────────────
# 分类规则配置由 /classify 模块统一管理，此处只负责触发执行

@router.get("/organize/status", dependencies=[Depends(verify_token)])
async def get_organize_status():
    """获取整理分类执行状态"""
    return await _organize_svc.get_status()


@router.post("/organize/run", dependencies=[Depends(verify_token)])
async def run_organize(payload: OrganizeRunPayload = None):
    """
    触发整理分类任务。
    payload.source_paths 可选；为空时从 path_mapping.organize_source 读取。
    """
    paths = (payload.source_paths or []) if payload else []
    return await _organize_svc.trigger_organize(source_paths=paths or None)




