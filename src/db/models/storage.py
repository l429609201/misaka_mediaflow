# app/db/models/storage.py
# 表 1: storageconfig — 存储源配置
# 表 2: pathmapping — 路径映射规则

from sqlalchemy import Column, BigInteger, Text

from src.db.base import Base
from src.db import get_id_column
from src.core.timezone import tm


class StorageConfig(Base):
    """存储源配置"""
    __tablename__ = "storageconfig"

    id         = get_id_column()
    name       = Column(Text, nullable=False, comment="存储名称")
    type       = Column(Text, nullable=False, comment="类型: clouddrive2/alist/p115")
    host       = Column(Text, nullable=False, comment="服务地址")
    config     = Column(Text, default="{}", comment="配置JSON，由适配器自定义字段")
    is_active  = Column(BigInteger, default=1, comment="是否启用: 1/0")
    created_at = Column(Text, default=tm.now, comment="创建时间")
    updated_at = Column(Text, default=tm.now, comment="更新时间")


class PathMapping(Base):
    """路径映射规则"""
    __tablename__ = "pathmapping"

    id              = get_id_column()
    storage_id      = Column(BigInteger, nullable=False, index=True, comment="关联存储源ID")
    local_prefix    = Column(Text, nullable=False, comment="本地路径前缀")
    cloud_prefix    = Column(Text, nullable=False, comment="云端路径前缀")
    priority        = Column(BigInteger, default=0, comment="优先级(数字越大越优先)")
    is_active       = Column(BigInteger, default=1, comment="是否启用: 1/0")
    created_at      = Column(Text, default=tm.now, comment="创建时间")

