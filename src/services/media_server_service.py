# src/services/media_server_service.py
# 统一媒体服务器服务层
#
# 职责：
#   · 从 SystemConfig 读取媒体服务器配置（host / api_key / type / user_id）
#   · 通过 MediaServerFactory 创建适配器实例（带进程级缓存）
#   · 暴露统一接口供上层调用（proxy_service / redirect_service / system API 等）
#   · 配置更新后通过 invalidate_cache() 刷新
#
# 调用方只需：
#   from src.services.media_server_service import media_server_service
#
#   cfg     = await media_server_service.get_config()
#   adapter = await media_server_service.get_adapter()
#   host, api_key = await media_server_service.get_host_and_key()

import logging
from typing import Optional

from sqlalchemy import select

from src.adapters.media_server.base import MediaServerAdapter
from src.adapters.media_server.factory import MediaServerFactory
from src.core.config import settings
from src.db import get_async_session_local
from src.db.models.system import SystemConfig

logger = logging.getLogger(__name__)

# ── 配置键常量（集中定义，避免各处硬编码字符串）────────────────────────────
MS_TYPE_KEY    = "media_server_type"
MS_HOST_KEY    = "media_server_host"
MS_APIKEY_KEY  = "media_server_api_key"
MS_USERID_KEY  = "media_server_user_id"

# 进程级适配器缓存（配置不变时复用同一实例）
_adapter_cache: Optional[MediaServerAdapter] = None
_config_cache:  Optional[dict] = None


class MediaServerService:
    """
    统一媒体服务器服务层。

    所有需要媒体服务器交互的服务（proxy_service / redirect_service /
    go_proxy_service / internal/emby 等）统一通过此服务调用，
    不直接读取 SystemConfig 或实例化具体适配器。
    """

    # ── 配置读取 ─────────────────────────────────────────────────────────────

    async def get_config(self) -> dict:
        """
        读取媒体服务器配置。优先从 SystemConfig 数据库读取，
        缺失字段用 config.yaml 默认值补齐。
        带进程级缓存，调用 invalidate_cache() 后下次会重新读取。
        """
        global _config_cache
        if _config_cache is not None:
            return _config_cache

        defaults = {
            "type":    settings.media_server.type,
            "host":    settings.media_server.host,
            "api_key": settings.media_server.api_key,
            "user_id": "",
        }

        key_map = {
            MS_TYPE_KEY:   "type",
            MS_HOST_KEY:   "host",
            MS_APIKEY_KEY: "api_key",
            MS_USERID_KEY: "user_id",
        }

        try:
            async with get_async_session_local() as db:
                for db_key, cfg_field in key_map.items():
                    row = await db.execute(
                        select(SystemConfig).where(SystemConfig.key == db_key)
                    )
                    rec = row.scalars().first()
                    if rec and rec.value:
                        defaults[cfg_field] = rec.value.strip().strip('"')
        except Exception as e:
            logger.warning("[media_server] 读取配置失败，使用默认值: %s", e)

        # host 去掉末尾斜线，便于直接拼接路径
        defaults["host"] = (defaults["host"] or "").rstrip("/")
        _config_cache = defaults
        return _config_cache

    async def save_config(self, cfg: dict) -> None:
        """
        保存媒体服务器配置到 SystemConfig，同时刷新缓存。

        Args:
            cfg: 包含 type / host / api_key / user_id 的字典
        """
        from src.core.timezone import tm

        saves = {
            MS_TYPE_KEY:   (cfg.get("type") or "emby").lower(),
            MS_HOST_KEY:   (cfg.get("host") or "").rstrip("/"),
            MS_APIKEY_KEY: cfg.get("api_key") or "",
            MS_USERID_KEY: cfg.get("user_id") or "",
        }

        async with get_async_session_local() as db:
            for k, v in saves.items():
                row = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == k)
                )
                rec = row.scalars().first()
                if rec:
                    rec.value = v
                    rec.updated_at = tm.now()
                else:
                    db.add(SystemConfig(
                        key=k, value=v,
                        description=f"媒体服务器配置: {k}",
                        updated_at=tm.now(),
                    ))
            await db.commit()

        self.invalidate_cache()
        logger.info(
            "[media_server] 配置已保存: type=%s host=%s",
            saves[MS_TYPE_KEY], saves[MS_HOST_KEY],
        )


    # ── 适配器获取 ───────────────────────────────────────────────────────────

    async def get_adapter(self) -> Optional[MediaServerAdapter]:
        """
        获取媒体服务器适配器实例（带进程级缓存）。
        配置不完整（host 或 api_key 为空）时返回 None。
        """
        global _adapter_cache
        if _adapter_cache is not None:
            return _adapter_cache

        cfg = await self.get_config()
        host    = cfg.get("host", "")
        api_key = cfg.get("api_key", "")
        stype   = cfg.get("type", "emby")

        if not host or not api_key:
            logger.warning("[media_server] 未配置 host 或 api_key，无法创建适配器")
            return None

        try:
            _adapter_cache = MediaServerFactory.create(
                server_type=stype, host=host, api_key=api_key
            )
            logger.debug("[media_server] 适配器已创建: type=%s", stype)
        except ValueError as e:
            logger.error("[media_server] 创建适配器失败: %s", e)
            return None

        return _adapter_cache

    async def get_adapter_with_params(
        self, host: str, api_key: str, server_type: str = "emby"
    ) -> MediaServerAdapter:
        """使用指定参数创建适配器（不经过缓存，用于测试连接等场景）"""
        return MediaServerFactory.create(
            server_type=server_type, host=host.rstrip("/"), api_key=api_key
        )

    # ── 便捷接口 ─────────────────────────────────────────────────────────────

    async def get_host_and_key(self) -> tuple[str, str]:
        """
        返回 (host, api_key) 元组，供 proxy_service / redirect_service 等直接使用。
        替代各处重复的 _get_media_server_config() 方法。
        """
        cfg = await self.get_config()
        return cfg.get("host", ""), cfg.get("api_key", "")

    async def get_libraries(self) -> list[dict]:
        """获取媒体库列表"""
        adapter = await self.get_adapter()
        if adapter is None:
            return []
        try:
            return await adapter.get_libraries()
        except Exception as e:
            logger.error("[media_server] 获取媒体库失败: %s", e)
            return []

    async def get_users(self) -> list[dict]:
        """获取用户列表"""
        adapter = await self.get_adapter()
        if adapter is None:
            return []
        try:
            return await adapter.get_users()
        except Exception as e:
            logger.error("[media_server] 获取用户列表失败: %s", e)
            return []

    async def test_connection(
        self, host: str, api_key: str, server_type: str = "emby"
    ) -> bool:
        """测试指定参数的连接是否可用"""
        try:
            adapter = await self.get_adapter_with_params(host, api_key, server_type)
            return await adapter.test_connection()
        except Exception as e:
            logger.warning("[media_server] 连接测试失败: %s", e)
            return False

    # ── 缓存管理 ─────────────────────────────────────────────────────────────

    def invalidate_cache(self) -> None:
        """
        清除适配器和配置缓存。
        配置更新后（save_config / system API 保存后）调用，
        确保下次使用时重新读取最新配置。
        """
        global _adapter_cache, _config_cache
        _adapter_cache = None
        _config_cache  = None
        logger.debug("[media_server] 缓存已清除")


# ── 全局单例 ──────────────────────────────────────────────────────────────────
# 整个进程共享同一实例，避免重复实例化适配器。
media_server_service = MediaServerService()
