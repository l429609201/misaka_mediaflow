# src/adapters/metadata/factory.py
# 元数据源工厂 — 动态扫描加载
#
# 新增元数据源只需:
#   1. 在 src/adapters/metadata/ 下新建 .py 文件
#   2. 继承 MetadataProvider，设置 PROVIDER_NAME
#   3. 完事。不需要改本文件。

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path

from src.adapters.metadata.base import MetadataProvider

logger = logging.getLogger(__name__)

# 动态扫描结果缓存
_REGISTRY: dict[str, type[MetadataProvider]] = {}
_scanned = False


def _scan_providers() -> None:
    """
    扫描 src/adapters/metadata/ 下所有模块，
    找到继承了 MetadataProvider 且设置了 PROVIDER_NAME 的类，自动注册。
    """
    global _scanned
    if _scanned:
        return
    _scanned = True

    package_dir = Path(__file__).parent
    package_name = "src.adapters.metadata"

    for finder, module_name, _is_pkg in pkgutil.iter_modules([str(package_dir)]):
        # 跳过 base / factory / __init__
        if module_name in ("base", "factory", "__init__"):
            continue
        try:
            module = importlib.import_module(f"{package_name}.{module_name}")
            for attr_name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, MetadataProvider)
                    and obj is not MetadataProvider
                    and getattr(obj, "PROVIDER_NAME", "")
                ):
                    name = obj.PROVIDER_NAME
                    _REGISTRY[name] = obj
                    logger.debug("[MetadataFactory] 自动注册: %s → %s", name, obj.__name__)
        except Exception as e:
            logger.warning("[MetadataFactory] 加载模块 %s 失败: %s", module_name, e)


class MetadataFactory:
    """元数据源工厂"""

    @staticmethod
    def create(provider_name: str, **kwargs) -> MetadataProvider:
        """
        创建新实例（配置通过 kwargs 注入）。

        Raises:
            ValueError: 不支持的元数据源
        """
        _scan_providers()
        cls = _REGISTRY.get(provider_name)
        if cls is None:
            raise ValueError(f"不支持的元数据源: {provider_name}，已注册: {list(_REGISTRY)}")
        return cls(**kwargs)

    @staticmethod
    def list_providers() -> list[dict]:
        """列出所有已注册的元数据源（供前端显示，含字段规格）"""
        _scan_providers()
        return [
            {
                "name": cls.PROVIDER_NAME,
                "label": cls.DISPLAY_NAME or cls.PROVIDER_NAME,
                "config_key": cls.CONFIG_KEY,
                "fields": [f.to_dict() for f in cls.CONFIG_FIELDS],
            }
            for cls in _REGISTRY.values()
        ]

    @staticmethod
    def get_provider_class(provider_name: str) -> type[MetadataProvider] | None:
        _scan_providers()
        return _REGISTRY.get(provider_name)

