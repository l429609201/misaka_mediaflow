# src/api/v1/gaps.py
# 缺集管理 API — 接入 TaskManager

from fastapi import APIRouter, Depends

from src.core.security import verify_token
from src.services.gaps_service import GapsService
from src.services.task_manager import get_task_manager

router = APIRouter(prefix="/gaps", tags=["缺集管理"])
_gaps_svc = GapsService()


@router.get("/scan", dependencies=[Depends(verify_token)])
async def scan_gaps(library_id: str = ""):
    """扫描缺集：先同步 Emby 再批量比对 TMDB — 记录任务"""
    tm = get_task_manager()
    task_id = await tm.create_task("缺集扫描", task_category="gaps", task_type="manual")

    try:
        tm.update_progress(task_id, "扫描中", {})
        result = await _gaps_svc.scan_gaps(library_id)

        if result.get("error"):
            await tm.complete_task(task_id, {"created": 0, "skipped": 0, "errors": 1}, result["error"])
        else:
            await tm.complete_task(task_id, {
                "created": result.get("gaps_count", 0),
                "skipped": result.get("skipped_no_tmdb", 0),
                "errors": 0,
            })

        result["task_id"] = task_id
        return result
    except Exception as e:
        await tm.complete_task(task_id, {"created": 0, "skipped": 0, "errors": 1}, str(e))
        return {"error": str(e), "task_id": task_id}
