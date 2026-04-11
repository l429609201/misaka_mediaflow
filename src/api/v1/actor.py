# src/api/v1/actor.py
# 演员管理 API — 耗时操作通过 TaskManager 记录

import asyncio
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.core.security import verify_token
from src.services.actor_service import get_actor_service
from src.services.task_manager import get_task_manager

router = APIRouter(prefix="/actor", tags=["演员管理"])


@router.get("/persons", dependencies=[Depends(verify_token)])
async def list_persons(
    search: str = Query("", description="搜索关键词"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    svc = get_actor_service()
    return await svc.get_all_persons(search=search, page=page, size=size)


@router.get("/orphans", dependencies=[Depends(verify_token)])
async def find_orphans():
    """查找黑户演员 — 后台任务"""
    tm = get_task_manager()
    svc = get_actor_service()
    task_id = await tm.create_task("黑户演员扫描", task_category="actor", task_type="manual")

    async def _run():
        try:
            tm.update_progress(task_id, "扫描中", {})
            orphans = await svc.find_orphan_actors()
            await tm.complete_task(task_id, {"created": len(orphans), "skipped": 0, "errors": 0})
            return orphans
        except Exception as e:
            await tm.complete_task(task_id, {"created": 0, "skipped": 0, "errors": 1}, str(e))
            return []

    orphans = await _run()
    return {"items": orphans, "total": len(orphans), "task_id": task_id}


@router.get("/ghosts", dependencies=[Depends(verify_token)])
async def find_ghosts(limit: int = Query(100, ge=1, le=500)):
    """查找幽灵演员 — 后台任务"""
    tm = get_task_manager()
    svc = get_actor_service()
    task_id = await tm.create_task("幽灵演员扫描", task_category="actor", task_type="manual")

    async def _run():
        try:
            tm.update_progress(task_id, "扫描中", {})
            ghosts = await svc.find_ghost_actors(limit=limit)
            await tm.complete_task(task_id, {"created": len(ghosts), "skipped": 0, "errors": 0})
            return ghosts
        except Exception as e:
            await tm.complete_task(task_id, {"created": 0, "skipped": 0, "errors": 1}, str(e))
            return []

    ghosts = await _run()
    return {"items": ghosts, "total": len(ghosts), "task_id": task_id}


@router.post("/translate", dependencies=[Depends(verify_token)])
async def translate_actor_names(limit: int = Query(200, ge=1, le=1000)):
    """演员名中文化 — 后台任务"""
    tm = get_task_manager()
    svc = get_actor_service()
    task_id = await tm.create_task("演员名中文化", task_category="actor", task_type="manual")

    async def _run():
        try:
            tm.update_progress(task_id, "翻译中", {})
            result = await svc.translate_names(limit=limit)
            await tm.complete_task(task_id, {
                "created": result.get("translated", 0),
                "skipped": result.get("skipped", 0),
                "errors": result.get("errors", 0),
            })
            return result
        except Exception as e:
            await tm.complete_task(task_id, {"created": 0, "skipped": 0, "errors": 1}, str(e))
            return {"success": False, "message": str(e)}

    result = await _run()
    result["task_id"] = task_id
    return result


@router.delete("/person/{person_id}", dependencies=[Depends(verify_token)])
async def delete_person(person_id: str):
    svc = get_actor_service()
    return await svc.delete_person(person_id)


class BatchDeletePayload(BaseModel):
    person_ids: list[str]


@router.post("/batch-delete", dependencies=[Depends(verify_token)])
async def batch_delete(payload: BatchDeletePayload):
    """批量删除演员 — 记录任务"""
    tm = get_task_manager()
    svc = get_actor_service()
    task_id = await tm.create_task(
        f"批量删除演员({len(payload.person_ids)}个)",
        task_category="actor", task_type="manual",
    )
    try:
        tm.update_progress(task_id, "删除中", {})
        result = await svc.batch_delete_persons(payload.person_ids)
        await tm.complete_task(task_id, {
            "created": result.get("deleted", 0),
            "skipped": 0,
            "errors": result.get("failed", 0),
        })
        result["task_id"] = task_id
        return result
    except Exception as e:
        await tm.complete_task(task_id, {"created": 0, "skipped": 0, "errors": 1}, str(e))
        return {"success": False, "message": str(e), "task_id": task_id}


@router.post("/cleanup", dependencies=[Depends(verify_token)])
async def cleanup_actors(mode: str = Query("ghost", description="orphan/ghost")):
    svc = get_actor_service()
    return await svc.cleanup(mode=mode)


class UpdatePersonPayload(BaseModel):
    name: str = ""
    provider_ids: dict = None


@router.post("/person/{person_id}/update", dependencies=[Depends(verify_token)])
async def update_person(person_id: str, payload: UpdatePersonPayload):
    svc = get_actor_service()
    return await svc.update_person(person_id, name=payload.name, provider_ids=payload.provider_ids)
