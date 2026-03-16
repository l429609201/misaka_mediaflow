# src/db/__init__.py
"""
数据库层 - 连接、模型、会话
对齐 misaka_danmu_server 的聚合导出模式

使用方式:
    from src.db import get_db_session
    from src.db import init_db_tables, close_db_engine
    from src.db import DatabaseStartupError
    from src.db import AsyncSessionLocal, SyncSessionLocal  # 兼容层
    from src.db import get_id_column, get_time_column
"""

from .database import (
    init_db_tables,
    close_db_engine,
    DatabaseStartupError,
    get_db_session,
    AsyncSessionLocal,
    SyncSessionLocal,
    get_async_session_local,
    get_id_column,
    get_time_column,
)

from .base import Base

__all__ = [
    # Database lifecycle
    "init_db_tables",
    "close_db_engine",
    "DatabaseStartupError",
    # Session
    "get_db_session",
    "AsyncSessionLocal",
    "SyncSessionLocal",
    "get_async_session_local",
    # Helpers
    "get_id_column",
    "get_time_column",
    # Base
    "Base",
]

