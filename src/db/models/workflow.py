# src/db/models/workflow.py
# 工作流 ORM 模型

from sqlalchemy import Column, BigInteger, String, Text, Integer

from src.db.base import Base
from src.db import get_id_column
from src.core.timezone import tm


class Workflow(Base):
    """工作流定义"""
    __tablename__ = "workflow"

    id          = get_id_column()
    name        = Column(String(255), nullable=False, default="", comment="工作流名称")
    description = Column(Text, default="", comment="描述")
    nodes       = Column(Text, default="[]", comment="节点列表 JSON")
    edges       = Column(Text, default="[]", comment="连线列表 JSON")
    viewport    = Column(Text, default="{}", comment="画布视口位置 JSON")
    enabled     = Column(Integer, default=1, comment="是否启用 1/0")
    cron        = Column(String(64), default="", comment="定时 cron 表达式，空=手动触发")
    created_at  = Column(Text, default=tm.now, comment="创建时间")
    updated_at  = Column(Text, default=tm.now, comment="更新时间")

    def to_dict(self):
        return {
            "id":          self.id,
            "name":        self.name,
            "description": self.description,
            "nodes":       self.nodes,
            "edges":       self.edges,
            "viewport":    self.viewport,
            "enabled":     self.enabled,
            "cron":        self.cron,
            "created_at":  self.created_at,
            "updated_at":  self.updated_at,
        }


class WorkflowExecution(Base):
    """工作流执行记录"""
    __tablename__ = "workflow_execution"

    id              = get_id_column()
    workflow_id     = Column(BigInteger, default=0, index=True, comment="关联工作流 ID")
    workflow_name   = Column(String(255), default="", comment="工作流名称快照")
    status          = Column(String(32), default="running", index=True, comment="running/completed/failed/cancelled")
    current_node    = Column(String(128), default="", comment="当前执行节点 ID")
    node_results    = Column(Text, default="{}", comment="各节点执行结果 JSON")
    error_message   = Column(Text, default="", comment="错误信息")
    triggered_by    = Column(String(32), default="manual", comment="manual/scheduled")
    started_at      = Column(Text, default="", comment="开始时间")
    finished_at     = Column(Text, default="", comment="结束时间")
    created_at      = Column(Text, default=tm.now, comment="创建时间")

    def to_dict(self):
        return {
            "id":             self.id,
            "workflow_id":    self.workflow_id,
            "workflow_name":  self.workflow_name,
            "status":         self.status,
            "current_node":   self.current_node,
            "node_results":   self.node_results,
            "error_message":  self.error_message,
            "triggered_by":   self.triggered_by,
            "started_at":     self.started_at,
            "finished_at":    self.finished_at,
            "created_at":     self.created_at,
        }
