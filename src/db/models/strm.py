# app/db/models/strm.py
# 表 5: strmtask — STRM 生成任务
# 表 6: strmfile — STRM 文件记录

from sqlalchemy import Column, BigInteger, String, Text

from src.db.base import Base
from src.db import get_id_column
from src.core.timezone import tm


class StrmTask(Base):
    """STRM 生成任务（通用任务中心）"""
    __tablename__ = "strmtask"

    id              = get_id_column()
    task_name       = Column(Text, default="", comment="任务显示名称: 全量STRM同步/增量STRM同步/整理分类")
    task_category   = Column(String(64), default="p115_strm", index=True, comment="任务分类: p115_strm/organize/manual")
    task_type       = Column(Text, default="manual", comment="触发方式: manual/scheduled/monitor")
    triggered_by    = Column(Text, default="manual", comment="触发来源: manual/scheduler/monitor")
    status          = Column(String(255), default="pending", index=True, comment="状态: pending/running/completed/failed")
    total_items     = Column(BigInteger, default=0, comment="总条目数")
    processed       = Column(BigInteger, default=0, comment="已处理数")
    created_count   = Column(BigInteger, default=0, comment="新增文件数")
    skipped_count   = Column(BigInteger, default=0, comment="跳过数")
    error_count     = Column(BigInteger, default=0, comment="失败数")
    error_message   = Column(Text, default="", comment="错误信息")
    extra_info      = Column(Text, default="", comment="额外信息 JSON（路径对、配置参数等）")
    started_at      = Column(Text, default="", comment="开始时间")
    finished_at     = Column(Text, default="", comment="结束时间")
    created_at      = Column(Text, default=tm.now, comment="创建时间")

    def to_dict(self):
        return {
            "id":            self.id,
            "task_name":     self.task_name,
            "task_category": self.task_category,
            "task_type":     self.task_type,
            "triggered_by":  self.triggered_by,
            "status":        self.status,
            "total_items":   self.total_items,
            "processed":     self.processed,
            "created_count": self.created_count,
            "skipped_count": self.skipped_count,
            "error_count":   self.error_count,
            "error_message": self.error_message,
            "extra_info":    self.extra_info,
            "started_at":    self.started_at,
            "finished_at":   self.finished_at,
            "created_at":    self.created_at,
        }


class StrmFile(Base):
    """STRM 文件记录"""
    __tablename__ = "strmfile"

    id          = get_id_column()
    task_id     = Column(BigInteger, default=0, index=True, comment="关联任务ID")
    item_id     = Column(String(255), nullable=False, index=True, comment="媒体条目ID")
    strm_path   = Column(Text, nullable=False, comment="STRM文件路径")
    strm_content = Column(Text, nullable=False, comment="STRM文件内容(URL或路径)")
    strm_mode   = Column(Text, default="proxy", comment="生成模式: proxy/direct/alist/p115/p115_path")
    file_size   = Column(BigInteger, default=0, comment="原始视频大小")
    created_at  = Column(Text, default=tm.now, comment="创建时间")

