# app/db/models/__init__.py
# 统一导出全部 ORM Model（含 user 表）

from src.db.models.storage import StorageConfig, PathMapping
from src.db.models.media import MediaItem
from src.db.models.cache import RedirectCache
from src.db.models.strm import StrmTask, StrmFile
from src.db.models.system import SystemConfig, OperationLog
from src.db.models.p115 import P115FsCache, P115MediaInfo, P115OrganizeRecord
from src.db.models.user import User

__all__ = [
    # 存储
    "StorageConfig",
    "PathMapping",
    # 媒体
    "MediaItem",
    # 缓存
    "RedirectCache",
    # STRM
    "StrmTask",
    "StrmFile",
    # 系统
    "SystemConfig",
    "OperationLog",
    # 115
    "P115FsCache",
    "P115MediaInfo",
    "P115OrganizeRecord",
    # 用户
    "User",
]

