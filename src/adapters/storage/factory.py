# app/adapters/storage/factory.py
# 存储工厂 — 根据类型创建对应适配器，并提供字段规格元信息

import logging
from src.adapters.storage.base import StorageAdapter, FieldSpec
from src.adapters.storage.clouddrive2 import CloudDrive2Adapter
from src.adapters.storage.alist import AlistAdapter
from src.adapters.storage.p115.p115_adapter import P115StorageAdapter
from src.adapters.storage.p115.p115_manager import P115Manager

logger = logging.getLogger(__name__)

# 注册表：type → 适配器类
_ADAPTER_REGISTRY: dict[str, type[StorageAdapter]] = {
    "clouddrive2": CloudDrive2Adapter,
    "alist":       AlistAdapter,
    "p115":        P115StorageAdapter,
}

# 前端显示用的类型标签
_TYPE_LABELS: dict[str, str] = {
    "clouddrive2": "CloudDrive2",
    "alist":       "Alist",
    "p115":        "115 网盘",
}


class StorageFactory:
    """存储适配器工厂"""

    @staticmethod
    def create(storage_type: str, host: str, config: dict) -> StorageAdapter:
        """
        根据类型创建适配器实例。
        所有认证/配置信息统一通过 config dict 传入，适配器自行解析。
        """
        if storage_type == "p115":
            manager = P115Manager()
            if not manager.enabled:
                manager.initialize()
            return manager.storage_adapter

        cls = _ADAPTER_REGISTRY.get(storage_type)
        if cls is None:
            raise ValueError(f"不支持的存储类型: {storage_type}")
        return cls(host=host, config=config)

    @staticmethod
    def get_meta() -> list[dict]:
        """
        返回所有存储类型的字段规格元信息，供前端动态渲染表单使用。
        格式：[{ type, label, fields: [FieldSpec.to_dict(), ...] }, ...]
        """
        meta = []
        for storage_type, cls in _ADAPTER_REGISTRY.items():
            meta.append({
                "type":   storage_type,
                "label":  _TYPE_LABELS.get(storage_type, storage_type),
                "fields": [f.to_dict() for f in cls.CONFIG_FIELDS],
            })
        return meta

    @staticmethod
    def get_fields(storage_type: str) -> list[FieldSpec]:
        """返回指定类型的字段规格列表"""
        cls = _ADAPTER_REGISTRY.get(storage_type)
        if cls is None:
            return []
        return cls.CONFIG_FIELDS

