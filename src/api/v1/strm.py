# app/api/v1/strm.py
# STRM 管理 API

from fastapi import APIRouter, Depends

from src.core.security import verify_token
from src.services.strm_service import StrmService

router = APIRouter(prefix="/strm", tags=["STRM 管理"])
_strm_service = StrmService()


@router.get("/tasks", dependencies=[Depends(verify_token)])
async def list_tasks(page: int = 1, size: int = 20):
    """分页获取 STRM 任务列表"""
    return await _strm_service.list_tasks(page, size)


@router.post("/tasks", dependencies=[Depends(verify_token)])
async def create_task(task_type: str = "manual"):
    """手动触发 STRM 生成"""
    return await _strm_service.create_task(task_type)


@router.get("/tasks/{task_id}", dependencies=[Depends(verify_token)])
async def get_task_status(task_id: int):
    """获取单个任务状态"""
    return await _strm_service.get_task_status(task_id)


@router.get("/files", dependencies=[Depends(verify_token)])
async def list_strm_files(task_id: int = 0, page: int = 1, size: int = 20):
    """分页获取 STRM 文件列表"""
    return await _strm_service.list_files(task_id, page, size)

