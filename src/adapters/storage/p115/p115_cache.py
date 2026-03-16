# app/adapters/storage/p115/p115_cache.py
# 115 ID ↔ Path 双向缓存

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class P115IdPathCache:
    """115 目录 ID ↔ 路径双向缓存（内存）"""

    def __init__(self):
        self._id_to_path: dict[str, str] = {}
        self._path_to_id: dict[str, str] = {}

    def put(self, file_id: str, path: str):
        self._id_to_path[file_id] = path
        self._path_to_id[path] = file_id

    def get_path(self, file_id: str) -> Optional[str]:
        return self._id_to_path.get(file_id)

    def get_id(self, path: str) -> Optional[str]:
        return self._path_to_id.get(path)

    def remove(self, file_id: str):
        path = self._id_to_path.pop(file_id, None)
        if path:
            self._path_to_id.pop(path, None)

    def clear(self):
        self._id_to_path.clear()
        self._path_to_id.clear()

    @property
    def size(self) -> int:
        return len(self._id_to_path)

