# src/services/notify_service.py
# 通知渠道服务
#
# 支持渠道：
#   - Telegram Bot（sendMessage API）
#   - Server酱（sc.ftqq.com / sct.ftqq.com）
#   - 自定义 Webhook（POST JSON）
#
# 配置存 SystemConfig 表，key = "notify_config"
# 格式：{ telegram: {enabled, token, chat_id}, serverchan: {enabled, key}, webhook: {enabled, url} }

import json
import logging
import time

import httpx

logger = logging.getLogger(__name__)

_cfg_cache: dict = {}
_cfg_cache_at: float = 0.0
_CFG_TTL = 60


async def _load_config() -> dict:
    global _cfg_cache, _cfg_cache_at
    now = time.monotonic()
    if _cfg_cache and now - _cfg_cache_at < _CFG_TTL:
        return _cfg_cache
    try:
        from src.db import get_async_session_local
        from src.db.models import SystemConfig
        from sqlalchemy import select
        async with get_async_session_local() as db:
            row = await db.execute(select(SystemConfig).where(SystemConfig.key == "notify_config"))
            cfg = row.scalars().first()
            if cfg and cfg.value:
                _cfg_cache = json.loads(cfg.value)
                _cfg_cache_at = now
                return _cfg_cache
    except Exception as e:
        logger.debug("[Notify] 配置加载失败: %s", e)
    return _cfg_cache or {}


async def save_config(config: dict) -> bool:
    """保存通知配置到 SystemConfig 表"""
    global _cfg_cache, _cfg_cache_at
    try:
        from src.db import get_async_session_local
        from src.db.models import SystemConfig
        from sqlalchemy import select
        async with get_async_session_local() as db:
            row = await db.execute(select(SystemConfig).where(SystemConfig.key == "notify_config"))
            obj = row.scalars().first()
            if obj:
                obj.value = json.dumps(config, ensure_ascii=False)
            else:
                obj = SystemConfig(key="notify_config", value=json.dumps(config, ensure_ascii=False))
                db.add(obj)
            await db.commit()
        _cfg_cache = config
        _cfg_cache_at = time.monotonic()
        return True
    except Exception as e:
        logger.error("[Notify] 保存配置失败: %s", e)
        return False


async def send(title: str, content: str = "") -> dict:
    """
    向所有已启用渠道发送通知。
    返回 {"telegram": bool, "serverchan": bool, "webhook": bool}
    """
    cfg = await _load_config()
    results = {}
    tasks = []

    tg = cfg.get("telegram", {})
    if tg.get("enabled") and tg.get("token") and tg.get("chat_id"):
        tasks.append(("telegram", _send_telegram(tg["token"], tg["chat_id"], title, content)))

    sc = cfg.get("serverchan", {})
    if sc.get("enabled") and sc.get("key"):
        tasks.append(("serverchan", _send_serverchan(sc["key"], title, content)))

    wh = cfg.get("webhook", {})
    if wh.get("enabled") and wh.get("url"):
        tasks.append(("webhook", _send_webhook(wh["url"], title, content)))

    import asyncio
    for name, coro in tasks:
        try:
            results[name] = await coro
        except Exception as e:
            logger.warning("[Notify] %s 发送失败: %s", name, e)
            results[name] = False

    if not results:
        logger.debug("[Notify] 未配置任何通知渠道，跳过")
    return results


async def _send_telegram(token: str, chat_id: str, title: str, content: str) -> bool:
    text = f"*{title}*" + (f"\n{content}" if content else "")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json={
            "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
        })
    ok = resp.status_code == 200 and resp.json().get("ok", False)
    logger.info("[Notify] Telegram %s: %s", "✅" if ok else "❌", resp.text[:200])
    return ok


async def _send_serverchan(key: str, title: str, content: str) -> bool:
    # 支持 SC3（sct.ftqq.com）和旧版（sc.ftqq.com）
    if key.startswith("SCT"):
        url = f"https://sctapi.ftqq.com/{key}.send"
    else:
        url = f"https://sc.ftqq.com/{key}.send"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, data={"title": title, "desp": content or title})
    ok = resp.status_code == 200
    logger.info("[Notify] Server酱 %s: %s", "✅" if ok else "❌", resp.text[:200])
    return ok


async def _send_webhook(url: str, title: str, content: str) -> bool:
    payload = {"title": title, "content": content, "time": int(time.time())}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload)
    ok = 200 <= resp.status_code < 300
    logger.info("[Notify] Webhook %s: status=%d", "✅" if ok else "❌", resp.status_code)
    return ok
