# app/adapters/storage/p115/p115_manager.py
# P115Manager — 115 模块统一管理器

import logging

from src.core.config import settings
from src.adapters.storage.p115.p115_auth import P115AuthService
from src.adapters.storage.p115.p115_adapter import P115StorageAdapter
from src.adapters.storage.p115.p115_cache import P115IdPathCache
from src.adapters.storage.p115.p115_rate import P115RateLimiter

logger = logging.getLogger(__name__)


class P115Manager:
    """115 模块统一管理器 — 整合认证/适配器/缓存/流控"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def initialize(self):
        """初始化 115 模块"""
        if self._initialized:
            return

        p115_config = settings.p115

        # 认证
        self.auth = P115AuthService()
        if p115_config.cookie:
            self.auth.set_cookie(p115_config.cookie)
        if p115_config.openapi.access_token:
            self.auth.set_openapi_tokens(
                p115_config.openapi.access_token,
                p115_config.openapi.refresh_token,
            )

        # 流控
        self.rate_limiter = P115RateLimiter(
            interval=p115_config.rate_limit.download_url_interval,
            waf_cooldown=p115_config.rate_limit.waf_cooldown,
        )

        # ID/Path 缓存
        self.id_path_cache = P115IdPathCache()

        # 存储适配器
        self.adapter = P115StorageAdapter(
            auth=self.auth,
            rate_limiter=self.rate_limiter,
            id_path_cache=self.id_path_cache,
        )

        self._initialized = True
        logger.info("115 模块初始化完成 (cookie=%s, openapi=%s)",
                     self.auth.has_cookie, self.auth.has_openapi)

    @property
    def enabled(self) -> bool:
        """配置是否启用 115 模块"""
        return settings.p115.enabled

    @property
    def ready(self) -> bool:
        """模块是否已初始化就绪"""
        return settings.p115.enabled and self._initialized

    @property
    def storage_adapter(self) -> P115StorageAdapter:
        return self.adapter

