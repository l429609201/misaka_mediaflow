# src/services/proxy_config_service.py
# 代理配置服务 — 负责 SystemConfig ↔ core.http_proxy 之间的桥梁
#
# 职责:
#   1. 从数据库加载代理配置 → 注入 core.http_proxy.configure()
#   2. 前端保存时写数据库 + 刷新 core 层配置
#   3. 应用启动时调 init_proxy_config() 完成初始化

import json
import logging

from sqlalchemy import select

from src.db import get_async_session_local
from src.db.models import SystemConfig
from src.core.timezone import tm
from src.core import http_proxy

logger = logging.getLogger(__name__)

_CONFIG_KEY = "http_proxy_settings"

_DEFAULTS = {
    "enabled": False,
    "proxy_url": "",
    "domains": [
        "api.themoviedb.org",
        "image.tmdb.org",
    ],
}


async def init_proxy_config() -> None:
    """
    应用启动时调用 — 从数据库加载代理配置并注入 core 层。

    在 main.py 的 startup 事件中调用。
    """
    cfg = await load_from_db()
    http_proxy.configure(cfg)
    logger.info("[proxy_config] 初始化完成: enabled=%s", cfg.get("enabled"))


async def load_from_db() -> dict:
    """从 SystemConfig 加载代理配置，缺失字段用默认值补齐"""
    try:
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _CONFIG_KEY)
            )
            cfg = result.scalars().first()
            if cfg and cfg.value:
                saved = json.loads(cfg.value)
                return {**_DEFAULTS, **saved}
    except Exception as e:
        logger.debug("[proxy_config] 加载异常: %s", e)

    return {**_DEFAULTS}


async def save_to_db(data: dict) -> None:
    """保存代理配置到 SystemConfig 并刷新 core 层"""
    merged = {**_DEFAULTS, **data}
    value = json.dumps(merged, ensure_ascii=False)

    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _CONFIG_KEY)
        )
        cfg = result.scalars().first()
        if cfg:
            cfg.value = value
            cfg.updated_at = tm.now()
        else:
            db.add(SystemConfig(
                key=_CONFIG_KEY,
                value=value,
                description="HTTP 代理中间件配置",
                updated_at=tm.now(),
            ))
        await db.commit()

    # 写完立即刷新 core 层内存配置
    http_proxy.configure(merged)
    logger.info("[proxy_config] 已保存并刷新: enabled=%s", merged.get("enabled"))

