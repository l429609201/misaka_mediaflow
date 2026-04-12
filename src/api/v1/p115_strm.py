# src/api/v1/p115_strm.py
# 115 STRM 同步 + 生活事件监控 + 整理分类 API

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional

from src.core.security import verify_token
from src.services.p115.strm_sync_service import P115StrmSyncService
from src.services.p115.life_monitor_service import get_life_monitor_service
from src.services.p115_organize_service import P115OrganizeService

router = APIRouter(prefix="/p115-strm", tags=["115 STRM 管理"])

_strm_sync_svc = P115StrmSyncService()
_organize_svc = P115OrganizeService()


# ─────────────────────── 请求体模型 ───────────────────────

class SyncPair(BaseModel):
    cloud_path: str   # 115 网盘路径（如 /媒体库）
    strm_path: str    # 本地 STRM 输出路径（如 /data/strm/媒体库）


class SyncDirCfg(BaseModel):
    """全量同步 / 增量同步 各自的自定义路径配置"""
    use_custom: bool = False   # 是否启用自定义路径（False 则沿用全局路径映射）
    cloud_path: str = ""       # 115 网盘路径（仅 use_custom=True 时生效）
    strm_path:  str = ""       # 本地 STRM 输出路径（仅 use_custom=True 时生效）


class StrmSyncConfigPayload(BaseModel):
    sync_pairs: List[SyncPair] = []
    file_extensions: str = "mp4,mkv,avi,ts,iso,mov,m2ts"
    strm_link_host: str = ""
    clean_invalid: bool = True
    # 全量 / 增量 各自的自定义路径配置
    full_sync_cfg: SyncDirCfg = SyncDirCfg()
    inc_sync_cfg:  SyncDirCfg = SyncDirCfg()
    # 全量同步覆盖模式
    full_overwrite_mode: str = "skip"
    # 刮削配置
    enable_scrape:         bool = False
    scrape_download_image: bool = True
    episode_group_id:      str  = ""
    # Cron 定时全量同步（5段 cron 表达式，空字符串=不启用）
    full_sync_cron: str = ""


class MonitorConfigPayload(BaseModel):
    # 兼容旧字段
    enabled: bool = True
    poll_interval: int = 30
    monitor_paths: List[str] = []
    auto_inc_sync: bool = True
    use_custom_dir: bool = False
    monitor_dir: Optional[str] = ""
    strm_dir: Optional[str] = ""
    # 新增：双通道配置
    life_poll_enabled: bool = True
    webhook_enabled:   bool = False
    webhook_token:     str  = ""
    trigger_types:     List[int] = []
    debounce_seconds:  int  = 5


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


@router.get("/sync/scan", dependencies=[Depends(verify_token)])
async def scan_local_strm(strm_root: str = None):
    """扫描本地 STRM 文件 — 后台任务，写入 StrmFile 表"""
    import asyncio
    from src.services.task_manager import get_task_manager

    tm = get_task_manager()
    task_id = await tm.create_task("STRM 扫描", task_category="p115_strm", task_type="manual")

    async def _bg():
        try:
            result = await _strm_sync_svc.scan_local_strm(strm_root, task_id=task_id)
            await tm.complete_task(task_id, {
                "created": result.get("total", 0),
                "skipped": result.get("invalid", 0),
                "errors": 0,
            })
        except Exception as e:
            await tm.complete_task(task_id, {"created": 0, "skipped": 0, "errors": 1}, str(e))

    bg = asyncio.create_task(_bg())
    tm.register_task(task_id, bg)
    return {"task_id": task_id, "message": "STRM 扫描已启动"}


class CleanStrmPayload(BaseModel):
    strm_root: Optional[str] = None
    dry_run: bool = True


@router.post("/sync/clean", dependencies=[Depends(verify_token)])
async def clean_invalid_strm(payload: CleanStrmPayload):
    """清理无效 STRM — 后台任务"""
    if payload.dry_run:
        return await _strm_sync_svc.clean_invalid_strm(strm_root=payload.strm_root, dry_run=True)

    import asyncio
    from src.services.task_manager import get_task_manager

    tm = get_task_manager()
    task_id = await tm.create_task("STRM 清理", task_category="p115_strm", task_type="manual")

    async def _bg():
        try:
            result = await _strm_sync_svc.clean_invalid_strm(strm_root=payload.strm_root, dry_run=False)
            await tm.complete_task(task_id, {
                "created": result.get("deleted_strm", 0),
                "skipped": 0, "errors": 0,
            })
        except Exception as e:
            await tm.complete_task(task_id, {"created": 0, "skipped": 0, "errors": 1}, str(e))

    bg = asyncio.create_task(_bg())
    tm.register_task(task_id, bg)
    return {"task_id": task_id, "message": "STRM 清理已启动"}


@router.post("/sync/rescrape", dependencies=[Depends(verify_token)])
async def rescrape_missing_nfo(strm_root: str = None):
    """补刮削 — 后台任务"""
    import asyncio
    from src.services.task_manager import get_task_manager

    tm = get_task_manager()
    task_id = await tm.create_task("补刮削 NFO", task_category="p115_strm", task_type="manual")

    async def _bg():
        try:
            result = await _strm_sync_svc.rescrape_missing_nfo(strm_root)
            await tm.complete_task(task_id, {
                "created": result.get("scraped", 0),
                "skipped": result.get("failed", 0),
                "errors": 0,
            })
        except Exception as e:
            await tm.complete_task(task_id, {"created": 0, "skipped": 0, "errors": 1}, str(e))

    bg = asyncio.create_task(_bg())
    tm.register_task(task_id, bg)
    return {"task_id": task_id, "message": "补刮削已启动"}


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




