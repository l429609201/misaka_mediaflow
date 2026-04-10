# src/api/v1/actor.py
# 演员管理 API

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.core.security import verify_token
from src.services.actor_service import get_actor_service

router = APIRouter(prefix="/actor", tags=["演员管理"])


@router.get("/persons", dependencies=[Depends(verify_token)])
async def list_persons():
    """获取 Emby 中所有演员"""
    svc = get_actor_service()
    persons = await svc.get_all_persons()
    return {"items": persons, "total": len(persons)}


@router.get("/orphans", dependencies=[Depends(verify_token)])
async def find_orphans():
    """查找黑户演员（没有关联任何媒体）"""
    svc = get_actor_service()
    orphans = await svc.find_orphan_actors()
    return {"items": orphans, "total": len(orphans)}


@router.get("/ghosts", dependencies=[Depends(verify_token)])
async def find_ghosts(limit: int = Query(100, ge=1, le=500)):
    """查找幽灵演员（TMDB 查不到的演员）"""
    svc = get_actor_service()
    ghosts = await svc.find_ghost_actors(limit=limit)
    return {"items": ghosts, "total": len(ghosts)}


@router.post("/translate", dependencies=[Depends(verify_token)])
async def translate_actor_names(limit: int = Query(200, ge=1, le=1000)):
    """演员名中文化"""
    svc = get_actor_service()
    return await svc.translate_names(limit=limit)


@router.delete("/person/{person_id}", dependencies=[Depends(verify_token)])
async def delete_person(person_id: str):
    """删除单个演员"""
    svc = get_actor_service()
    return await svc.delete_person(person_id)


class BatchDeletePayload(BaseModel):
    person_ids: list[str]


@router.post("/batch-delete", dependencies=[Depends(verify_token)])
async def batch_delete(payload: BatchDeletePayload):
    """批量删除演员"""
    svc = get_actor_service()
    return await svc.batch_delete_persons(payload.person_ids)


@router.post("/cleanup", dependencies=[Depends(verify_token)])
async def cleanup_actors(mode: str = Query("ghost", description="orphan/ghost")):
    """清理演员（仅检测并返回列表，不自动删除）"""
    svc = get_actor_service()
    return await svc.cleanup(mode=mode)
