# app/db/models/cache.py
# 表 4: redirectcache — 302 直链缓存（DB 持久层）

from sqlalchemy import Column, BigInteger, String, Text

from src.db.base import Base
from src.db import get_id_column
from src.core.timezone import tm


class RedirectCache(Base):
    """302 直链缓存"""
    __tablename__ = "redirectcache"

    id          = get_id_column()
    cache_key   = Column(String(255), nullable=False, unique=True, comment="SHA256缓存键")
    item_id     = Column(String(255), nullable=False, index=True, comment="媒体条目ID")
    storage_id  = Column(BigInteger, default=0, comment="存储源ID")
    direct_url  = Column(Text, nullable=False, comment="直链URL")
    expires_at  = Column(String(255), nullable=False, index=True, comment="过期时间")
    hit_count   = Column(BigInteger, default=0, comment="命中次数")
    created_at  = Column(Text, default=tm.now, comment="创建时间")

