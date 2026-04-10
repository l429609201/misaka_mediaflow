# src/api/v1/workflow.py
# 工作流 API — CRUD + 执行 + 节点类型

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional

from src.core.security import verify_token
from src.services.workflow_service import get_workflow_engine

router = APIRouter(prefix="/workflow", tags=["工作流"])


# ── 节点类型 ──────────────────────────────────────────────────────────

@router.get("/node-types", dependencies=[Depends(verify_token)])
async def get_node_types():
    """获取所有可用的工作流节点类型"""
    engine = get_workflow_engine()
    return {"items": engine.get_available_node_types()}


# ── 工作流 CRUD ──────────────────────────────────────────────────────

@router.get("", dependencies=[Depends(verify_token)])
async def list_workflows():
    """列出所有工作流"""
    engine = get_workflow_engine()
    items = await engine.list_workflows()
    return {"items": items}


@router.get("/{wf_id}", dependencies=[Depends(verify_token)])
async def get_workflow(wf_id: int):
    """获取单个工作流详情"""
    engine = get_workflow_engine()
    data = await engine.get_workflow(wf_id)
    if not data:
        return {"error": "工作流不存在"}
    return data


class WorkflowPayload(BaseModel):
    id: Optional[int] = None
    name: str = "新工作流"
    description: str = ""
    nodes: list = []
    edges: list = []
    viewport: dict = {}
    enabled: int = 1
    cron: str = ""


@router.post("", dependencies=[Depends(verify_token)])
async def save_workflow(payload: WorkflowPayload):
    """创建或更新工作流"""
    engine = get_workflow_engine()
    data = payload.model_dump()
    result = await engine.save_workflow(data)
    return result


@router.delete("/{wf_id}", dependencies=[Depends(verify_token)])
async def delete_workflow(wf_id: int):
    """删除工作流"""
    engine = get_workflow_engine()
    await engine.delete_workflow(wf_id)
    return {"success": True}


# ── 执行 ──────────────────────────────────────────────────────────────

@router.post("/{wf_id}/execute", dependencies=[Depends(verify_token)])
async def execute_workflow(wf_id: int):
    """执行工作流"""
    engine = get_workflow_engine()
    return await engine.execute_workflow(wf_id)


@router.get("/executions/list", dependencies=[Depends(verify_token)])
async def list_executions(
    workflow_id: int = Query(0),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """查询执行记录"""
    engine = get_workflow_engine()
    return await engine.list_executions(workflow_id, page, size)


@router.post("/executions/{exe_id}/cancel", dependencies=[Depends(verify_token)])
async def cancel_execution(exe_id: int):
    """取消执行"""
    engine = get_workflow_engine()
    return await engine.cancel_execution(exe_id)
