# src/services/p115_warmup_service.py
# P115Client 预热服务 — 应用启动时提前创建 P115Client 实例
#
# 解决的问题：
#   P115Client(cookie) 构造时内部会做 RSA 密钥初始化等耗时操作（约 200-500ms）。
#   若不预热，第一次 302 请求会在 _get_p115_client() 中触发冷启动，
#   造成首播延迟。
#
# 调用时机：
#   main.py lifespan 中，在 Cookie 加载完成后（init_proxy_config 之后）调用。

import asyncio
import logging

logger = logging.getLogger(__name__)


async def warmup_p115_client() -> None:
    """
    预热 P115Client。
    - 确保 P115Manager 已初始化
    - 从数据库加载 Cookie（若 config.yaml 未配置）
    - 在线程池内调用 adapter.warmup()，提前完成 P115Client 构造
    """
    try:
        from src.adapters.storage.p115 import P115Manager
        from src.db import get_async_session_local
        from src.db.models import SystemConfig
        from sqlalchemy import select

        manager = P115Manager()
        if not manager.enabled:
            logger.info("[预热] 115 模块未启用，跳过 P115Client 预热")
            return

        # 确保已初始化
        if not manager.ready:
            manager.initialize()

        # 从数据库补充 Cookie（config.yaml 未配置时）
        if not manager.auth.has_cookie:
            try:
                async with get_async_session_local() as db:
                    row = await db.execute(
                        select(SystemConfig).where(SystemConfig.key == "p115_cookie")
                    )
                    cfg = row.scalars().first()
                    if cfg and cfg.value:
                        cookie_val = cfg.value.strip().strip('"').strip("'")
                        manager.auth.set_cookie(cookie_val)
                        logger.info(
                            "[预热] 从数据库加载 Cookie 成功 (len=%d)", len(cookie_val)
                        )
            except Exception as e:
                logger.warning("[预热] 从数据库加载 Cookie 失败: %s", e)

        if not manager.auth.has_cookie:
            logger.info("[预热] Cookie 未就绪，P115Client 预热延迟到首次请求时触发")
            return

        # 在线程池内执行 warmup（P115Client 构造是同步阻塞操作）
        ok = await asyncio.to_thread(manager.adapter.warmup)
        if ok:
            logger.info("[预热] ✅ P115Client 预热完成，首次 302 将无冷启动延迟")
        else:
            logger.warning("[预热] P115Client 预热失败，首次 302 仍会触发冷启动")

    except Exception as e:
        # 预热失败不影响主流程
        logger.warning("[预热] P115Client 预热异常（不影响服务启动）: %s", e)

