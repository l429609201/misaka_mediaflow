# src/core/http_proxy.py
# 通用 HTTP 代理中间件 — 纯逻辑层，零外部依赖
#
# 设计原则:
#   core 层不依赖 db / services，配置由外部注入（configure）。
#   启动时由 service 层从 SystemConfig 加载后调 configure() 写入。
#   运行时前端保存设置后也调 configure() 刷新。
#
# 用法:
#   from src.core.http_proxy import proxy_client, get_proxy_for_url, configure
#
#   # 启动时注入配置（由 service 层负责）
#   configure({"enabled": True, "proxy_url": "http://127.0.0.1:7890",
#              "domains": ["api.themoviedb.org"]})
#
#   # 方式1: 上下文管理器（自动判断是否需代理）
#   async with proxy_client("https://api.themoviedb.org/3/movie/550") as client:
#       resp = await client.get(url)
#
#   # 方式2: 同步判断
#   proxy_url = get_proxy_for_url("https://api.themoviedb.org/3/...")

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
#  模块级配置（由外部注入，core 层不碰数据库）
# ──────────────────────────────────────────────────────────────────────

_config: dict = {
    "enabled": False,
    "proxy_url": "",
    "domains": [],
}


def configure(cfg: dict) -> None:
    """
    注入 / 刷新代理配置。

    由 service 层在以下时机调用:
      1. 应用启动时从 SystemConfig 加载后
      2. 前端保存代理设置后

    Args:
        cfg: {"enabled": bool, "proxy_url": str, "domains": list[str]}
    """
    global _config
    _config = {
        "enabled": bool(cfg.get("enabled", False)),
        "proxy_url": (cfg.get("proxy_url") or "").strip(),
        "domains": list(cfg.get("domains") or []),
    }
    if _config["enabled"]:
        logger.info("[proxy] 配置已注入: url=%s, domains=%s",
                     _config["proxy_url"], _config["domains"])


def get_config() -> dict:
    """获取当前代理配置的只读副本"""
    return {**_config}


# ──────────────────────────────────────────────────────────────────────
#  核心：域名匹配
# ──────────────────────────────────────────────────────────────────────

def get_proxy_for_url(url: str) -> str | None:
    """
    根据 URL 域名判断是否需要走代理（同步，零 IO）。

    返回代理地址或 None。
    匹配规则: hostname 精确匹配或是 domains 列表中某条的子域名。
    """
    if not _config["enabled"] or not _config["proxy_url"]:
        return None

    try:
        hostname = (urlparse(url).hostname or "").lower()
    except Exception:
        return None

    for domain in _config["domains"]:
        d = (domain or "").lower().strip()
        if not d:
            continue
        if hostname == d or hostname.endswith("." + d):
            return _config["proxy_url"]

    return None


def match_domain(url: str) -> bool:
    """判断 URL 是否命中代理域名列表（不关心是否 enabled）"""
    try:
        hostname = (urlparse(url).hostname or "").lower()
    except Exception:
        return False

    for domain in _config["domains"]:
        d = (domain or "").lower().strip()
        if d and (hostname == d or hostname.endswith("." + d)):
            return True
    return False


# ──────────────────────────────────────────────────────────────────────
#  上下文管理器：自动代理的 httpx Client
# ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def proxy_client(
    target_url: str = "",
    timeout: float = 15,
    **kwargs,
):
    """
    获取 httpx.AsyncClient，自动根据 target_url 决定是否走代理。

    - 传了 target_url → 按域名匹配
    - 不传 → enabled=True 时全部走代理
    """
    p = None
    if target_url:
        p = get_proxy_for_url(target_url)
    elif _config["enabled"] and _config["proxy_url"]:
        p = _config["proxy_url"]

    client_kwargs = {"timeout": timeout, **kwargs}
    if p:
        client_kwargs["proxy"] = p
        logger.debug("[proxy] %s → %s", target_url[:60] if target_url else "*", p)

    async with httpx.AsyncClient(**client_kwargs) as client:
        yield client

