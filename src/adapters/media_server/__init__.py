# app/adapters/media_server/__init__.py
# 媒体服务器适配器统一导出

from src.adapters.media_server.base import MediaServerAdapter
from src.adapters.media_server.emby import EmbyAdapter
from src.adapters.media_server.jellyfin import JellyfinAdapter

__all__ = [
    "MediaServerAdapter",
    "EmbyAdapter",
    "JellyfinAdapter",
]

