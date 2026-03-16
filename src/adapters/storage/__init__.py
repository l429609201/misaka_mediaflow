# app/adapters/storage/__init__.py
# 存储适配器层统一导出

from src.adapters.storage.base import StorageAdapter, DirectLink, FileEntry
from src.adapters.storage.factory import StorageFactory
from src.adapters.storage.clouddrive2 import CloudDrive2Adapter
from src.adapters.storage.alist import AlistAdapter
from src.adapters.storage.p115 import P115Manager, P115StorageAdapter

__all__ = [
    "StorageAdapter",
    "DirectLink",
    "FileEntry",
    "StorageFactory",
    "CloudDrive2Adapter",
    "AlistAdapter",
    "P115Manager",
    "P115StorageAdapter",
]

