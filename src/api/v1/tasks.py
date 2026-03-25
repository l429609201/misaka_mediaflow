# src/api/v1/tasks.py
# 任务中心 API — 查询/删除 StrmTask 历史记录 + 实时运行快照

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, delete

from src.core.security import verify_token
from src.db import get_async_session_local
from src.db.models.strm import StrmTask
from src.services.task_manager import get_task_manager

router = APIRouter(prefix="/tasks", tags=["任务中心"])


# ── 分页查询历史任务 ──────────────────────────────────────────────

@router.get("", dependencies=[Depends(verify_token)])
async def list_tasks(
    page:     int = Query(1,  ge=1),
    size:     int = Query(20, ge=1, le=100),
    category: str = Query("", description="按分类过滤: p115_strm/organize/all"),
    status:   str = Query("", description="按状态过滤: running/completed/failed/all"),
):
    """分页查询所有历史任务，最新在前"""
    async with get_async_session_local() as db:
        q = select(StrmTask)
        c = select(func.count()).select_from(StrmTask)

        if category and category != "all":
            q = q.where(StrmTask.task_category == category)
            c = c.where(StrmTask.task_category == category)
        if status and status != "all":
            q = q.where(StrmTask.status == status)
            c = c.where(StrmTask.status == status)

        total = (await db.execute(c)).scalar() or 0
        rows  = (await db.execute(
            q.order_by(StrmTask.id.desc())
             .offset((page - 1) * size)
             .limit(size)
        )).scalars().all()

    # 注入实时进度
    tm    = get_task_manager()
    items = []
    for row in rows:
        d = row.to_dict()
        live = tm.get_live(row.id)
        if live:
            d["live_stats"] = live
        items.append(d)

    return {"items": items, "total": total, "page": page, "size": size}


# ── 运行中任务快照 ────────────────────────────────────────────────

@router.get("/running", dependencies=[Depends(verify_token)])
async def get_running_tasks():
    """获取当前所有运行中任务的实时快照（内存，响应极快）"""
    tm = get_task_manager()
    return {"items": tm.get_running()}


# ── 单任务详情 ────────────────────────────────────────────────────

@router.get("/{task_id}", dependencies=[Depends(verify_token)])
async def get_task(task_id: int):
    """获取单个任务详情（含实时进度）"""
    async with get_async_session_local() as db:
        task = await db.get(StrmTask, task_id)
    if not task:
        return {"error": "任务不存在"}
    d = task.to_dict()
    live = get_task_manager().get_live(task_id)
    if live:
        d["live_stats"] = live
    return d


# ── 终止运行中任务 ────────────────────────────────────────────────

@router.post("/{task_id}/cancel", dependencies=[Depends(verify_token)])
async def cancel_task(task_id: int):
    """终止运行中的任务（发送取消信号，并将任务状态标记为 failed）"""
    tm = get_task_manager()
    if not tm.get_live(task_id):
        return {"success": False, "message": "任务未在运行中"}
    cancelled = tm.cancel_task(task_id)
    if cancelled:
        # 更新 DB：状态标记为 failed，写入终止原因
        async with get_async_session_local() as db:
            task = await db.get(StrmTask, task_id)
            if task:
                from src.core.timezone import tm as tz
                task.status        = "failed"
                task.error_message = "用户手动终止"
                task.finished_at   = tz.now()
                await db.commit()
        # 清理内存快照（asyncio.Task 取消后协程会抛 CancelledError，_live 也会被 complete_task 清理）
        # 这里提前清理以防 complete_task 因异常路径无法执行
        tm._live.pop(task_id, None)
        tm._tasks.pop(task_id, None)
        return {"success": True, "message": "任务已终止"}
    return {"success": False, "message": "终止失败，任务可能已结束"}


# ── 删除任务记录 ──────────────────────────────────────────────────

@router.delete("/{task_id}", dependencies=[Depends(verify_token)])
async def delete_task(task_id: int):
    """删除指定任务记录（运行中任务不可删除）"""
    tm = get_task_manager()
    if tm.get_live(task_id):
        return {"success": False, "message": "任务正在运行中，不可删除"}
    async with get_async_session_local() as db:
        await db.execute(delete(StrmTask).where(StrmTask.id == task_id))
        await db.commit()
    return {"success": True}


# ── 批量删除已完成任务 ────────────────────────────────────────────

@router.delete("", dependencies=[Depends(verify_token)])
async def clear_finished_tasks(
    category: str = Query("", description="按分类清除，空=全部"),
    status:   str = Query("completed", description="清除哪种状态: completed/failed/all"),
):
    """批量清除已完成/失败的历史任务记录"""
    async with get_async_session_local() as db:
        q = delete(StrmTask)
        if category and category != "all":
            q = q.where(StrmTask.task_category == category)
        if status and status != "all":
            q = q.where(StrmTask.status == status)
        else:
            # 只删除非运行中
            q = q.where(StrmTask.status.in_(["completed", "failed"]))
        result = await db.execute(q)
        await db.commit()
    return {"success": True, "deleted": result.rowcount}

