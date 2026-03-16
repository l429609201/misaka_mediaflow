# app/schemas/__init__.py
# Pydantic 模型统一导出

from src.schemas.storage import StorageConfigCreate, StorageConfigOut, PathMappingCreate, PathMappingOut
from src.schemas.common import PageQuery, PageResult, ResponseModel

__all__ = [
    "StorageConfigCreate",
    "StorageConfigOut",
    "PathMappingCreate",
    "PathMappingOut",
    "PageQuery",
    "PageResult",
    "ResponseModel",
]

