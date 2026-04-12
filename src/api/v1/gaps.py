# src/api/v1/gaps.py
# 缺集管理 API — 后台异步执行 + 实时进度

import asyncio

from fastapi import APIRouter, Depends

from src.core.security import verify_token
from src.services.gaps_service import GapsService
from src.services.task_manager import get_task_manager

router = APIRouter(prefix="/gaps", tags=["缺集管理"])
_gaps_svc = GapsService()


async def _run_scan(task_id: int, library_id: str):
    """后台执行缺集扫描，实时更新进度"""
    tm = get_task_manager()
    try:
        result = await _gaps_svc.scan_gaps(library_id, task_id=task_id)
        if result.get("error"):
            await tm.complete_task(task_id, {"created": 0, "skipped": 0, "errors": 1}, result["error"])
        else:
            await tm.complete_task(task_id, {
                "created": result.get("gaps_count", 0),
                "skipped": result.get("skipped_no_tmdb", 0),
                "errors": 0,
            })
    except Exception as e:
        await tm.complete_task(task_id, {"created": 0, "skipped": 0, "errors": 1}, str(e))


@router.get("/scan", dependencies=[Depends(verify_token)])
async def scan_gaps(library_id: str = ""):
    """扫描缺集 — 后台异步执行，立即返回 task_id"""
    tm = get_task_manager()
    task_id = await tm.create_task("缺集扫描", task_category="gaps", task_type="manual")
    tm.update_progress(task_id, "启动中", {})

    bg_task = asyncio.create_task(_run_scan(task_id, library_id))
    tm.register_task(task_id, bg_task)

    return {"task_id": task_id, "message": "缺集扫描已启动"}


@router.get("/list", dependencies=[Depends(verify_token)])
async def list_gaps():
    """查询缺集数据 — 直接从 DB 读取，不触发扫描"""
    return await _gaps_svc.get_gaps_from_db()
