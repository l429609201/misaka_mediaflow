# src/services/task_manager.py
# 统一任务管理器 — 单例，负责创建/更新/完成 StrmTask 记录
# 并在内存中维护运行中任务的实时进度（供 API 快速查询）

import asyncio
import json
import logging
from typing import Optional

from src.core.timezone import tm
from src.db import get_async_session_local
from src.db.models.strm import StrmTask

logger = logging.getLogger(__name__)


class TaskManager:
    """统一任务管理器（单例）

    职责：
    1. 创建任务记录（写 DB）
    2. 更新进度（内存 + DB）
    3. 标记完成/失败（写 DB）
    4. 提供运行中任务的内存快照（供实时 API 读取）
    5. 支持终止运行中任务（cancel asyncio.Task）
    """

    def __init__(self):
        # {task_id: {pct, stage, stats, ...}}  — 仅运行中任务保留
        self._live: dict[int, dict] = {}
        # {task_id: asyncio.Task}  — 存储 asyncio.Task 引用，供 cancel 使用
        self._tasks: dict[int, asyncio.Task] = {}

    # ── 创建任务 ────────────────────────────────────────────────

    async def create_task(
        self,
        task_name: str,
        task_category: str = "p115_strm",
        task_type: str = "manual",
        triggered_by: str = "manual",
        extra_info: dict | None = None,
    ) -> int:
        """在 DB 中创建任务记录，返回 task_id"""
        async with get_async_session_local() as db:
            task = StrmTask(
                task_name=task_name,
                task_category=task_category,
                task_type=task_type,
                triggered_by=triggered_by,
                status="running",
                started_at=tm.now(),
                extra_info=json.dumps(extra_info or {}, ensure_ascii=False),
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)
            task_id = task.id

        self._live[task_id] = {
            "task_name": task_name,
            "task_category": task_category,
            "stage": "running",
            "created": 0, "skipped": 0, "errors": 0,
        }
        logger.debug("TaskManager: 创建任务 id=%d name=%s", task_id, task_name)
        return task_id

    # ── 更新进度 ────────────────────────────────────────────────

    def update_progress(self, task_id: int, stage: str, stats: dict):
        """更新内存中任务进度（高频调用，不写 DB）"""
        if task_id in self._live:
            self._live[task_id].update({"stage": stage, **stats})

    # ── 完成任务 ────────────────────────────────────────────────

    async def complete_task(
        self,
        task_id: int,
        stats: dict,
        error_message: str = "",
    ):
        """将任务标记为 completed/failed，写入 DB，清理内存"""
        status = "failed" if error_message else "completed"
        async with get_async_session_local() as db:
            task = await db.get(StrmTask, task_id)
            if task:
                task.status        = status
                task.created_count = stats.get("created", 0)
                task.skipped_count = stats.get("skipped", 0)
                task.error_count   = stats.get("errors", 0)
                task.error_message = error_message
                task.finished_at   = tm.now()
                await db.commit()

        self._live.pop(task_id, None)
        self._tasks.pop(task_id, None)
        logger.debug("TaskManager: 完成任务 id=%d status=%s", task_id, status)

    # ── 任务注册与取消 ──────────────────────────────────────────

    def register_task(self, task_id: int, task: asyncio.Task) -> None:
        """注册 asyncio.Task 引用，供 cancel_task 使用"""
        self._tasks[task_id] = task
        logger.debug("TaskManager: 注册 asyncio.Task id=%d", task_id)

    def cancel_task(self, task_id: int) -> bool:
        """取消运行中的 asyncio.Task，返回是否成功发出取消信号"""
        task = self._tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            logger.info("TaskManager: 已发出取消信号 id=%d", task_id)
            return True
        logger.warning("TaskManager: 取消失败(任务不存在或已结束) id=%d", task_id)
        return False

    async def force_delete_task(self, task_id: int) -> dict:
        """强制删除任务：cancel 协程 → 更新 DB 状态 → 清内存 → 删 DB 记录

        不论任务处于什么状态都会删除。
        """
        from sqlalchemy import delete as sa_delete

        # 1) 若运行中，先发 cancel 信号
        atask = self._tasks.get(task_id)
        if atask and not atask.done():
            atask.cancel()
            logger.info("TaskManager: force_delete 已发出取消信号 id=%d", task_id)

        # 2) 强制把 DB 状态置为 failed（防止协程在 CancelledError 路径中漏掉更新）
        async with get_async_session_local() as db:
            task_row = await db.get(StrmTask, task_id)
            if task_row and task_row.status == "running":
                task_row.status        = "failed"
                task_row.error_message = "用户强制删除"
                task_row.finished_at   = tm.now()
                await db.commit()

        # 3) 清理内存
        self._live.pop(task_id, None)
        self._tasks.pop(task_id, None)

        # 4) 删除 DB 记录
        async with get_async_session_local() as db:
            await db.execute(sa_delete(StrmTask).where(StrmTask.id == task_id))
            await db.commit()

        logger.info("TaskManager: 任务已强制删除 id=%d", task_id)
        return {"success": True, "message": "任务已强制删除"}

    # ── 查询 ────────────────────────────────────────────────────

    def get_running(self) -> list[dict]:
        """返回所有运行中任务的快照（含实时进度）"""
        return [{"task_id": tid, **info} for tid, info in self._live.items()]

    def get_live(self, task_id: int) -> Optional[dict]:
        """获取单个运行中任务的实时状态"""
        return self._live.get(task_id)


# ── 全局单例 ────────────────────────────────────────────────────
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager

