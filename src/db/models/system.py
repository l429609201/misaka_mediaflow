# app/db/models/system.py
# 表 7: systemconfig — 系统配置 KV
# 表 8: operationlog — 操作日志

from sqlalchemy import Column, BigInteger, String, Text

from src.db.base import Base
from src.db import get_id_column
from src.core.timezone import tm


class SystemConfig(Base):
    """系统配置 — 通用 KV 存储"""
    __tablename__ = "systemconfig"

    id          = get_id_column()
    key         = Column(String(255), nullable=False, unique=True, comment="配置键")
    value       = Column(Text, default="", comment="配置值(JSON)")
    description = Column(Text, default="", comment="描述")
    updated_at  = Column(Text, default=tm.now, comment="更新时间")


class OperationLog(Base):
    """操作日志"""
    __tablename__ = "operationlog"

    id          = get_id_column()
    module      = Column(String(255), default="", index=True, comment="模块: proxy/strm/storage/p115/system")
    action      = Column(Text, default="", comment="动作: create/update/delete/sync/redirect")
    detail      = Column(Text, default="", comment="详情")
    ip_address  = Column(Text, default="", comment="IP地址")
    created_at  = Column(Text, default=tm.now, comment="记录时间")

