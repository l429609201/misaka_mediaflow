# app/adapters/media_server/base.py
# 媒体服务器适配器抽象基类

from abc import ABC, abstractmethod
from typing import Optional


class MediaServerAdapter(ABC):
    """Emby / Jellyfin 抽象基类"""

    @abstractmethod
    async def get_libraries(self) -> list[dict]:
        """获取媒体库列表"""
        ...

    @abstractmethod
    async def get_items(self, library_id: str, item_type: Optional[str] = None) -> list[dict]:
        """获取媒体条目"""
        ...

    @abstractmethod
    async def get_item_detail(self, item_id: str) -> dict:
        """获取单个条目详情"""
        ...

    @abstractmethod
    async def get_playback_info(self, item_id: str) -> dict:
        """获取播放信息（MediaSources）"""
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """测试连接"""
        ...

