# app/db/models/user.py
# 表: user — 用户账号管理

from sqlalchemy import Column, BigInteger, String, Text

from src.db.base import Base
from src.db import get_id_column
from src.core.timezone import tm


class User(Base):
    """用户表 — 账号密码独立管理"""
    __tablename__ = "user"

    id            = get_id_column()
    username      = Column(String(255), nullable=False, unique=True, comment="用户名")
    password_hash = Column(Text, nullable=False, comment="密码哈希")
    role          = Column(String(50), default="admin", comment="角色: admin/user")
    is_active     = Column(BigInteger, default=1, comment="是否激活: 1/0")
    created_at    = Column(Text, default=tm.now, comment="创建时间")
    updated_at    = Column(Text, default=tm.now, comment="更新时间")

