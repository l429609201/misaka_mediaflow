# app/adapters/storage/p115/p115_rate.py
# 115 流控 / 熔断保护 — 参考 emby-toolkit / p115disk

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class P115RateLimiter:
    """115 API 流控器"""

    def __init__(self, interval: float = 1.5, waf_cooldown: float = 10.0):
        self._interval = interval
        self._waf_cooldown = waf_cooldown
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()
        self._is_waf_blocked = False
        self._waf_until: float = 0.0

    async def acquire(self):
        """获取调用许可，确保间隔合规"""
        async with self._lock:
            now = time.monotonic()
            # WAF 封禁检查
            if self._is_waf_blocked and now < self._waf_until:
                wait = self._waf_until - now
                logger.warning(f"115 WAF 冷却中，等待 {wait:.1f}s")
                await asyncio.sleep(wait)
                self._is_waf_blocked = False

            # 频率限制
            elapsed = now - self._last_call
            if elapsed < self._interval:
                await asyncio.sleep(self._interval - elapsed)
            self._last_call = time.monotonic()

    def trigger_waf_cooldown(self):
        """触发 WAF 冷却"""
        self._is_waf_blocked = True
        self._waf_until = time.monotonic() + self._waf_cooldown
        logger.warning(f"115 WAF 触发，冷却 {self._waf_cooldown}s")

    @property
    def is_blocked(self) -> bool:
        return self._is_waf_blocked and time.monotonic() < self._waf_until

