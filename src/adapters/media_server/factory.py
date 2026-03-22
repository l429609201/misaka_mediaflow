# src/adapters/media_server/factory.py
# 媒体服务器适配器工厂
#
# 职责：
#   根据 server_type 字符串创建对应的 MediaServerAdapter 实例。
#   所有调用方只需：
#     from src.adapters.media_server.factory import MediaServerFactory
#     adapter = MediaServerFactory.create("emby", host=host, api_key=api_key)
#
# 扩展方式：
#   新增媒体服务器类型时，只需在 _REGISTRY 中添加对应映射，
#   上层服务无需任何修改。

import logging

from src.adapters.media_server.base import MediaServerAdapter
from src.adapters.media_server.emby import EmbyAdapter
from src.adapters.media_server.jellyfin import JellyfinAdapter

logger = logging.getLogger(__name__)

# 注册表：server_type → 适配器类
_REGISTRY: dict[str, type[MediaServerAdapter]] = {
    "emby":     EmbyAdapter,
    "jellyfin": JellyfinAdapter,
}

# 各类型的显示名称
_TYPE_LABELS: dict[str, str] = {
    "emby":     "Emby",
    "jellyfin": "Jellyfin",
}


class MediaServerFactory:
    """媒体服务器适配器工厂"""

    @staticmethod
    def create(server_type: str, host: str, api_key: str) -> MediaServerAdapter:
        """
        根据类型创建适配器实例。

        Args:
            server_type: 服务器类型，如 'emby' / 'jellyfin'
            host:        服务器地址，如 'http://127.0.0.1:8096'
            api_key:     API Key

        Returns:
            MediaServerAdapter 实例

        Raises:
            ValueError: 不支持的服务器类型
        """
        server_type = (server_type or "emby").lower().strip()
        cls = _REGISTRY.get(server_type)
        if cls is None:
            supported = list(_REGISTRY.keys())
            raise ValueError(
                f"不支持的媒体服务器类型: {server_type!r}，"
                f"已支持: {supported}"
            )
        logger.debug(
            "[MediaServerFactory] 创建适配器: type=%s host=%s",
            server_type, host
        )
        return cls(host=host, api_key=api_key)

    @staticmethod
    def list_types() -> list[dict]:
        """列出所有支持的服务器类型（供前端下拉选择）"""
        return [
            {"value": k, "label": _TYPE_LABELS.get(k, k)}
            for k in _REGISTRY
        ]

    @staticmethod
    def is_supported(server_type: str) -> bool:
        """检查是否支持该服务器类型"""
        return (server_type or "").lower().strip() in _REGISTRY

