# src/services/workflow_service.py
# 工作流执行引擎 — 按 DAG 拓扑排序执行节点链

import asyncio
import json
import logging
from typing import Optional
from collections import defaultdict

from src.core.timezone import tm
from src.db import get_async_session_local
from src.db.models.workflow import Workflow, WorkflowExecution

logger = logging.getLogger(__name__)


# ── 节点类型注册表 ────────────────────────────────────────────────────
# 每种节点类型对应一个 async handler(ctx, params) -> result_dict
_NODE_HANDLERS: dict[str, callable] = {}


def register_node(node_type: str):
    """装饰器：注册工作流节点处理器"""
    def decorator(func):
        _NODE_HANDLERS[node_type] = func
        return func
    return decorator


# ── 内置节点 ──────────────────────────────────────────────────────────

@register_node("start")
async def _handle_start(ctx: dict, params: dict) -> dict:
    return {"status": "ok", "message": "工作流开始"}


@register_node("end")
async def _handle_end(ctx: dict, params: dict) -> dict:
    return {"status": "ok", "message": "工作流结束"}


@register_node("delay")
async def _handle_delay(ctx: dict, params: dict) -> dict:
    seconds = int(params.get("seconds", 5))
    await asyncio.sleep(seconds)
    return {"status": "ok", "delayed": seconds}


@register_node("log")
async def _handle_log(ctx: dict, params: dict) -> dict:
    msg = params.get("message", "")
    logger.info("[工作流日志] %s", msg)
    return {"status": "ok", "message": msg}


@register_node("strm_full_sync")
async def _handle_strm_full(ctx: dict, params: dict) -> dict:
    """触发 115 STRM 全量同步"""
    try:
        from src.services.p115.strm_sync_service import StrmSyncService
        svc = StrmSyncService()
        result = await svc.full_sync()
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_node("strm_inc_sync")
async def _handle_strm_inc(ctx: dict, params: dict) -> dict:
    """触发 115 STRM 增量同步"""
    try:
        from src.services.p115.strm_sync_service import StrmSyncService
        svc = StrmSyncService()
        result = await svc.inc_sync()
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_node("organize")
async def _handle_organize(ctx: dict, params: dict) -> dict:
    """触发整理分类"""
    try:
        from src.services.p115_organize_service import P115OrganizeService
        svc = P115OrganizeService()
        result = await svc.run_organize()
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_node("refresh_library")
async def _handle_refresh_library(ctx: dict, params: dict) -> dict:
    """刷新媒体库"""
    try:
        from src.services.media_server_service import media_server_service
        adapter = await media_server_service.get_adapter()
        if adapter and hasattr(adapter, '_ensure_client'):
            client = await adapter._ensure_client()
            resp = await client.post("/emby/Library/Refresh")
            return {"status": "ok", "http_status": resp.status_code}
        return {"status": "error", "message": "媒体服务器未配置"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_node("notify")
async def _handle_notify(ctx: dict, params: dict) -> dict:
    """发送通知"""
    try:
        from src.services.notify_service import notify_service
        title = params.get("title", "工作流通知")
        body = params.get("body", "工作流执行完成")
        await notify_service.send(title, body)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_node("actor_cleanup")
async def _handle_actor_cleanup(ctx: dict, params: dict) -> dict:
    """演员清理"""
    try:
        from src.services.actor_service import actor_service
        mode = params.get("mode", "ghost")
        result = await actor_service.cleanup(mode=mode)
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_node("actor_translate")
async def _handle_actor_translate(ctx: dict, params: dict) -> dict:
    """演员中文化"""
    try:
        from src.services.actor_service import actor_service
        result = await actor_service.translate_names()
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_node("condition")
async def _handle_condition(ctx: dict, params: dict) -> dict:
    """条件分支 — 根据表达式决定走 true/false 分支"""
    field = params.get("field", "")
    op = params.get("operator", "eq")
    value = params.get("value", "")
    actual = ctx.get("prev_result", {}).get(field, "")
    result = False


# ── 拓扑排序 + 执行引擎 ─────────────────────────────────────────────

def _topo_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
    """将节点按 DAG 拓扑排序，返回 node_id 列表"""
    in_deg = defaultdict(int)
    adj = defaultdict(list)
    node_ids = {n["id"] for n in nodes}
    for n_id in node_ids:
        in_deg[n_id] = 0
    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        if src in node_ids and tgt in node_ids:
            adj[src].append(tgt)
            in_deg[tgt] += 1
    queue = [n for n in node_ids if in_deg[n] == 0]
    result = []
    while queue:
        queue.sort()
        node = queue.pop(0)
        result.append(node)
        for nxt in adj[node]:
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                queue.append(nxt)
    return result


class WorkflowEngine:
    """工作流执行引擎（单例）"""

    def __init__(self):
        self._running: dict[int, asyncio.Task] = {}

    # ── CRUD ──────────────────────────────────────────────────────────

    async def list_workflows(self) -> list[dict]:
        async with get_async_session_local() as db:
            from sqlalchemy import select as sa_select
            rows = (await db.execute(
                sa_select(Workflow).order_by(Workflow.id.desc())
            )).scalars().all()
            return [r.to_dict() for r in rows]

    async def get_workflow(self, wf_id: int) -> Optional[dict]:
        async with get_async_session_local() as db:
            wf = await db.get(Workflow, wf_id)
            return wf.to_dict() if wf else None

    async def save_workflow(self, data: dict) -> dict:
        async with get_async_session_local() as db:
            wf_id = data.get("id")
            if wf_id:
                wf = await db.get(Workflow, wf_id)
                if wf:
                    wf.name = data.get("name", wf.name)
                    wf.description = data.get("description", wf.description)
                    wf.nodes = json.dumps(data.get("nodes", []), ensure_ascii=False)
                    wf.edges = json.dumps(data.get("edges", []), ensure_ascii=False)
                    wf.viewport = json.dumps(data.get("viewport", {}), ensure_ascii=False)
                    wf.enabled = data.get("enabled", wf.enabled)
                    wf.cron = data.get("cron", wf.cron)
                    wf.updated_at = tm.now()
                    await db.commit()
                    await db.refresh(wf)
                    return wf.to_dict()
            # 新建
            wf = Workflow(
                name=data.get("name", "新工作流"),
                description=data.get("description", ""),
                nodes=json.dumps(data.get("nodes", []), ensure_ascii=False),
                edges=json.dumps(data.get("edges", []), ensure_ascii=False),
                viewport=json.dumps(data.get("viewport", {}), ensure_ascii=False),
                enabled=data.get("enabled", 1),
                cron=data.get("cron", ""),
            )
            db.add(wf)
            await db.commit()
            await db.refresh(wf)
            return wf.to_dict()

    async def delete_workflow(self, wf_id: int) -> bool:
        from sqlalchemy import delete as sa_delete
        async with get_async_session_local() as db:
            await db.execute(sa_delete(Workflow).where(Workflow.id == wf_id))
            await db.commit()
        return True

    # ── 执行 ──────────────────────────────────────────────────────────

    async def execute_workflow(self, wf_id: int, triggered_by: str = "manual") -> dict:
        wf_data = await self.get_workflow(wf_id)
        if not wf_data:
            return {"success": False, "message": "工作流不存在"}

        # 创建执行记录
        async with get_async_session_local() as db:
            exe = WorkflowExecution(
                workflow_id=wf_id,
                workflow_name=wf_data["name"],
                status="running",
                triggered_by=triggered_by,
                started_at=tm.now(),
            )
            db.add(exe)
            await db.commit()
            await db.refresh(exe)
            exe_id = exe.id

        # 异步执行
        task = asyncio.create_task(self._run(exe_id, wf_data))
        self._running[exe_id] = task
        return {"success": True, "execution_id": exe_id}

    async def _run(self, exe_id: int, wf_data: dict):
        nodes = json.loads(wf_data.get("nodes", "[]")) if isinstance(wf_data.get("nodes"), str) else wf_data.get("nodes", [])
        edges = json.loads(wf_data.get("edges", "[]")) if isinstance(wf_data.get("edges"), str) else wf_data.get("edges", [])
        node_map = {n["id"]: n for n in nodes}
        sorted_ids = _topo_sort(nodes, edges)

        ctx = {"workflow_id": wf_data["id"], "prev_result": {}}
        node_results = {}
        error_msg = ""

        try:
            for node_id in sorted_ids:
                node = node_map.get(node_id)
                if not node:
                    continue
                node_type = node.get("data", {}).get("type", node.get("type", ""))
                params = node.get("data", {}).get("params", {})
                handler = _NODE_HANDLERS.get(node_type)

                # 更新当前节点
                async with get_async_session_local() as db:
                    exe = await db.get(WorkflowExecution, exe_id)
                    if exe:
                        exe.current_node = node_id
                        exe.node_results = json.dumps(node_results, ensure_ascii=False)
                        await db.commit()

                if not handler:
                    node_results[node_id] = {"status": "skipped", "message": f"未知节点类型: {node_type}"}
                    continue

                logger.info("工作流[%s] 执行节点 %s (%s)", wf_data["name"], node_id, node_type)
                result = await handler(ctx, params)
                node_results[node_id] = result
                ctx["prev_result"] = result

                if result.get("status") == "error":
                    error_msg = f"节点 {node_id}({node_type}) 失败: {result.get('message', '')}"
                    break

        except asyncio.CancelledError:
            error_msg = "用户取消"
        except Exception as e:
            error_msg = str(e)
            logger.exception("工作流执行异常: %s", e)
        finally:
            status = "failed" if error_msg else "completed"
            async with get_async_session_local() as db:
                exe = await db.get(WorkflowExecution, exe_id)
                if exe:
                    exe.status = status
                    exe.node_results = json.dumps(node_results, ensure_ascii=False)
                    exe.error_message = error_msg
                    exe.finished_at = tm.now()
                    await db.commit()
            self._running.pop(exe_id, None)

    # ── 查询执行记录 ──────────────────────────────────────────────────

    async def list_executions(self, wf_id: int = 0, page: int = 1, size: int = 20) -> dict:
        from sqlalchemy import select as sa_select, func
        async with get_async_session_local() as db:
            q = sa_select(WorkflowExecution)
            c = sa_select(func.count()).select_from(WorkflowExecution)
            if wf_id:
                q = q.where(WorkflowExecution.workflow_id == wf_id)
                c = c.where(WorkflowExecution.workflow_id == wf_id)
            total = (await db.execute(c)).scalar() or 0
            rows = (await db.execute(
                q.order_by(WorkflowExecution.id.desc()).offset((page - 1) * size).limit(size)
            )).scalars().all()
            return {"items": [r.to_dict() for r in rows], "total": total, "page": page}

    async def cancel_execution(self, exe_id: int) -> dict:
        task = self._running.get(exe_id)
        if task and not task.done():
            task.cancel()
            return {"success": True, "message": "已发送取消信号"}
        return {"success": False, "message": "执行不存在或已结束"}

    def get_running(self) -> list[int]:
        return list(self._running.keys())

    @staticmethod
    def get_available_node_types() -> list[dict]:
        """返回所有可用的节点类型"""
        _LABELS = {
            "start": {"label": "开始", "category": "flow", "color": "#52c41a"},
            "end": {"label": "结束", "category": "flow", "color": "#ff4d4f"},
            "delay": {"label": "延时等待", "category": "flow", "color": "#faad14"},
            "log": {"label": "日志输出", "category": "flow", "color": "#1677ff"},
            "condition": {"label": "条件分支", "category": "flow", "color": "#722ed1"},
            "strm_full_sync": {"label": "STRM 全量同步", "category": "task", "color": "#13c2c2"},
            "strm_inc_sync": {"label": "STRM 增量同步", "category": "task", "color": "#13c2c2"},
            "organize": {"label": "整理分类", "category": "task", "color": "#eb2f96"},
            "refresh_library": {"label": "刷新媒体库", "category": "task", "color": "#2f54eb"},
            "notify": {"label": "发送通知", "category": "task", "color": "#fa8c16"},
            "actor_cleanup": {"label": "演员清理", "category": "actor", "color": "#a0d911"},
            "actor_translate": {"label": "演员中文化", "category": "actor", "color": "#a0d911"},
        }
        result = []
        for ntype in _NODE_HANDLERS:
            info = _LABELS.get(ntype, {"label": ntype, "category": "other", "color": "#999"})
            result.append({"type": ntype, **info})
        return result


# ── 全局单例 ──────────────────────────────────────────────────────────
_engine: Optional[WorkflowEngine] = None

def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine
