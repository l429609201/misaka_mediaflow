# app/services/__init__.py
# 业务逻辑层统一导出

from src.services.strm_service import StrmService
from src.services.proxy_service import ProxyService
from src.services.p115_service import P115Service
from src.services.log_manager import setup_logging

__all__ = [
    "StrmService",
    "ProxyService",
    "P115Service",
    "setup_logging",
]

