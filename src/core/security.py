# app/core/security.py
# 认证系统 — 用户名密码登录 + JWT Token + API Token
# 初始化时如果没有密码，自动随机生成并打印到控制台

import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.core.config import settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# ==================== 常量 ====================

ADMIN_USERNAME = "admin"
JWT_EXPIRE_SECONDS = 7 * 24 * 3600   # 7 天


# ==================== 密码工具 ====================


def hash_password(password: str) -> str:
    """SHA256 哈希密码（加盐）"""
    salt = "mediaflow_salt_2025"
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    """验证密码"""
    return hmac.compare_digest(hash_password(plain), hashed)


# ==================== JWT（HMAC-SHA256，零依赖） ====================


def _b64url_encode(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    import base64
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _get_jwt_secret() -> str:
    return get_api_token()


def create_jwt_token(username: str) -> str:
    """创建 JWT Token"""
    secret = _get_jwt_secret()
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload_data = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRE_SECONDS,
    }
    payload = _b64url_encode(json.dumps(payload_data).encode())
    signing_input = f"{header}.{payload}"
    sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url_encode(sig)}"


def decode_jwt_token(token: str) -> Optional[dict]:
    """解码并验证 JWT Token，失败返回 None"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_part, payload_part, sig_part = parts
        secret = _get_jwt_secret()
        signing_input = f"{header_part}.{payload_part}"
        expected = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        actual = _b64url_decode(sig_part)
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(payload_part))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ==================== API Token（持久化） ====================

_runtime_api_token: Optional[str] = None


def get_api_token() -> str:
    """
    获取 API Token。
    优先级：配置文件 > 内存缓存（由 async_preload_from_db 在启动时填充）> 随机生成。
    注意：DB 持久化由 async_preload_from_db 在异步上下文完成，此函数纯内存操作。
    """
    global _runtime_api_token

    # 1. 配置文件优先
    if settings.security.api_token:
        return settings.security.api_token

    # 2. 内存缓存（由 async_preload_from_db 在启动时填充）
    if _runtime_api_token is not None:
        return _runtime_api_token

    # 3. 兜底：生成临时 token（启动预加载尚未完成时极少数情况）
    #    不持久化，持久化由 async_preload_from_db 负责
    _runtime_api_token = secrets.token_urlsafe(32)
    logger.warning("API Token 在预加载前被访问，使用临时 token（将在预加载后被覆盖）")
    return _runtime_api_token


# ==================== 管理员密码管理（user 表） ====================

_initial_password: Optional[str] = None
_admin_password_hash: Optional[str] = None


def initialize_admin_password():
    """
    同步兼容入口（被 main.py lifespan 调用）。
    实际 DB 操作已移至 async_preload_from_db，此函数仅作兼容占位：
    若预加载已完成（_admin_password_hash 已填充），直接返回；
    否则生成随机密码放入内存（DB 持久化由 async_preload_from_db 在之后完成）。
    """
    global _initial_password, _admin_password_hash

    # 配置文件优先（不需要 DB）
    configured = getattr(settings.security, "admin_password", "")
    if configured:
        _admin_password_hash = hash_password(configured)
        logger.info("管理员密码已从配置加载")
        return

    # async_preload_from_db 已经填充过了，直接返回
    if _admin_password_hash is not None:
        return

    # 兜底：生成随机密码（正常启动流程下 async_preload_from_db 先于此函数运行）
    _initial_password = secrets.token_urlsafe(12)
    _admin_password_hash = hash_password(_initial_password)
    print("\n" + "=" * 60)
    print("  Misaka MediaFlow 初始管理员账户")
    print(f"   用户名: {ADMIN_USERNAME}")
    print(f"   密码:   {_initial_password}")
    print("   请登录后在设置页面修改密码!")
    print("=" * 60 + "\n")
    logger.info("初始管理员密码已随机生成（详见控制台输出）")


def get_admin_password_hash() -> str:
    global _admin_password_hash
    if _admin_password_hash is None:
        initialize_admin_password()
    return _admin_password_hash


async def reload_admin_password_from_db() -> Optional[str]:
    """
    实时从 user 表读取最新密码 hash，更新内存缓存并返回。
    用于登录失败时兜底：外部脚本(reset_password)改了数据库后
    无需重启服务即可生效。不受配置文件写死密码影响。
    """
    global _admin_password_hash
    try:
        from src.db import get_async_session_local
        from src.db.models import User
        from sqlalchemy import select
        async with get_async_session_local() as db:
            result = await db.execute(
                select(User).where(User.username == ADMIN_USERNAME)
            )
            user = result.scalars().first()
            if user and user.password_hash:
                _admin_password_hash = user.password_hash
                logger.debug("管理员密码已从数据库实时刷新")
                return _admin_password_hash
    except Exception as e:
        logger.warning("实时刷新密码失败: %s", e)
    return None


async def update_admin_password(new_password: str):
    """更新管理员密码（异步写入 user 表）"""
    global _admin_password_hash
    _admin_password_hash = hash_password(new_password)
    # 清除配置文件的"写死密码"优先级，让内存以此次修改为准
    # 之后 reload_admin_password_from_db 也能从数据库读到最新值
    try:
        settings.security.admin_password = ""
    except Exception:
        pass
    try:
        from src.db import get_async_session_local
        from src.db.models import User
        from src.core.timezone import tm
        from sqlalchemy import select
        now = tm.now()
        async with get_async_session_local() as db:
            result = await db.execute(select(User).where(User.username == ADMIN_USERNAME))
            user = result.scalars().first()
            if user:
                user.password_hash = _admin_password_hash
                user.updated_at = now
            else:
                user = User(
                    username=ADMIN_USERNAME,
                    password_hash=_admin_password_hash,
                    role="admin", is_active=1,
                    created_at=now, updated_at=now,
                )
                db.add(user)
            await db.commit()
            logger.info("管理员密码已更新")
    except Exception as e:
        logger.error("密码更新失败: %s", e)


# ==================== IP 白名单（从数据库 systemconfig 表读取） ====================

# 内存缓存，避免每次请求都查数据库
_whitelist_cache: list = []
_whitelist_cache_ts: float = 0


async def _load_whitelist_from_db_async() -> list:
    """从 systemconfig 表异步读取白名单，更新内存缓存"""
    import json as _json
    import time as _time
    global _whitelist_cache, _whitelist_cache_ts
    try:
        from src.db import get_async_session_local
        from src.db.models import SystemConfig
        from sqlalchemy import select
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == "ip_whitelist")
            )
            cfg = result.scalars().first()
            _whitelist_cache = _json.loads(cfg.value) if (cfg and cfg.value) else []
            _whitelist_cache_ts = _time.time()
    except Exception:
        pass
    return _whitelist_cache


def _load_whitelist_from_db() -> list:
    """
    从内存缓存返回白名单（同步只读）。
    缓存由 async_preload_from_db 在启动时填充，invalidate_whitelist_cache
    清零后下次 async 请求时由 _check_ip_whitelist 触发异步刷新。
    """
    return _whitelist_cache


def invalidate_whitelist_cache():
    """清除白名单缓存（修改后调用，下次请求触发异步重新加载）"""
    global _whitelist_cache_ts
    _whitelist_cache_ts = 0


async def _check_ip_whitelist_async(client_ip: str) -> bool:
    """
    检查 IP 是否在白名单中（异步版本，缓存过期时自动刷新）。
    支持 CIDR 格式，兼容 IPv6 ::1 → 127.0.0.1。
    """
    import ipaddress
    import time as _time

    # 缓存过期则异步刷新
    if not _whitelist_cache_ts or _time.time() - _whitelist_cache_ts >= 10:
        await _load_whitelist_from_db_async()

    whitelist = _whitelist_cache
    if not whitelist:
        return False

    # ::ffff:127.0.0.1 / ::1 统一映射为 127.0.0.1
    normalized = client_ip
    if normalized == "::1":
        normalized = "127.0.0.1"
    if normalized.startswith("::ffff:"):
        normalized = normalized[7:]

    try:
        addr = ipaddress.ip_address(normalized)
        for entry in whitelist:
            try:
                entry_str = str(entry).strip()
                if entry_str in ("::1",):
                    entry_str = "127.0.0.1"
                if entry_str.startswith("::ffff:"):
                    entry_str = entry_str[7:]
                if '/' in entry_str:
                    if addr in ipaddress.ip_network(entry_str, strict=False):
                        return True
                else:
                    if addr == ipaddress.ip_address(entry_str):
                        return True
            except ValueError:
                continue
    except ValueError:
        return False
    return False


def _check_ip_whitelist(client_ip: str) -> bool:
    """同步兼容版本（只读内存缓存，不触发 DB 查询）"""
    import ipaddress
    whitelist = _whitelist_cache
    if not whitelist:
        return False

    normalized = client_ip
    if normalized == "::1":
        normalized = "127.0.0.1"
    if normalized.startswith("::ffff:"):
        normalized = normalized[7:]

    try:
        addr = ipaddress.ip_address(normalized)
        for entry in whitelist:
            try:
                entry_str = str(entry).strip()
                if entry_str in ("::1",):
                    entry_str = "127.0.0.1"
                if entry_str.startswith("::ffff:"):
                    entry_str = entry_str[7:]
                if '/' in entry_str:
                    if addr in ipaddress.ip_network(entry_str, strict=False):
                        return True
                else:
                    if addr == ipaddress.ip_address(entry_str):
                        return True
            except ValueError:
                continue
    except ValueError:
        return False
    return False


# ==================== 启动时异步预加载（替代同步 DB 操作） ====================

async def async_preload_from_db(session_factory) -> None:
    """
    在 lifespan 启动阶段（init_db_tables → _setup_compat）异步预加载所有
    security 模块需要的数据，消除对同步 PostgreSQL 驱动的依赖。

    加载顺序：
    1. api_token：从 systemconfig 表读取，不存在则随机生成并写入
    2. admin_password_hash：从 user 表读取，不存在则生成随机密码并写入
    3. ip_whitelist：从 systemconfig 表读取，写入内存缓存
    """
    global _runtime_api_token, _admin_password_hash, _initial_password
    global _whitelist_cache, _whitelist_cache_ts

    import json as _json
    import time as _time
    from sqlalchemy import select
    from src.db.models import SystemConfig, User
    from src.core.timezone import tm

    try:
        async with session_factory() as db:
            # 1. api_token
            if not settings.security.api_token:
                result = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == "api_token")
                )
                cfg = result.scalars().first()
                if cfg and cfg.value:
                    _runtime_api_token = cfg.value
                    logger.info("API Token 已从数据库预加载")
                else:
                    _runtime_api_token = secrets.token_urlsafe(32)
                    now = tm.now()
                    new_cfg = SystemConfig(
                        key="api_token", value=_runtime_api_token,
                        description="API Token / JWT Secret（自动生成）", updated_at=now,
                    )
                    db.add(new_cfg)
                    await db.commit()
                    logger.info("API Token 已自动生成并持久化")

            # 2. admin_password（配置文件优先，无需 DB）
            configured = getattr(settings.security, "admin_password", "")
            if configured:
                _admin_password_hash = hash_password(configured)
                # 同步到 user 表
                result = await db.execute(
                    select(User).where(User.username == ADMIN_USERNAME)
                )
                user = result.scalars().first()
                now = tm.now()
                if user:
                    user.password_hash = _admin_password_hash
                    user.updated_at = now
                else:
                    db.add(User(
                        username=ADMIN_USERNAME, password_hash=_admin_password_hash,
                        role="admin", is_active=1, created_at=now, updated_at=now,
                    ))
                await db.commit()
                logger.info("管理员密码已从配置同步到 user 表")
            else:
                result = await db.execute(
                    select(User).where(User.username == ADMIN_USERNAME)
                )
                user = result.scalars().first()
                if user and user.password_hash:
                    _admin_password_hash = user.password_hash
                    logger.info("管理员密码已从 user 表预加载")
                else:
                    _initial_password = secrets.token_urlsafe(12)
                    _admin_password_hash = hash_password(_initial_password)
                    now = tm.now()
                    if user:
                        user.password_hash = _admin_password_hash
                        user.updated_at = now
                    else:
                        db.add(User(
                            username=ADMIN_USERNAME, password_hash=_admin_password_hash,
                            role="admin", is_active=1, created_at=now, updated_at=now,
                        ))
                    await db.commit()
                    print("\n" + "=" * 60)
                    print("  Misaka MediaFlow 初始管理员账户")
                    print(f"   用户名: {ADMIN_USERNAME}")
                    print(f"   密码:   {_initial_password}")
                    print("   请登录后在设置页面修改密码!")
                    print("=" * 60 + "\n")
                    logger.info("初始管理员密码已随机生成并写入 user 表")

            # 3. ip_whitelist
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == "ip_whitelist")
            )
            wl_cfg = result.scalars().first()
            _whitelist_cache = _json.loads(wl_cfg.value) if (wl_cfg and wl_cfg.value) else []
            _whitelist_cache_ts = _time.time()

    except Exception as e:
        logger.error("security 预加载失败: %s", e)
        # 不抛异常：允许服务降级启动，缺失数据由各函数兜底处理


# ==================== FastAPI 依赖项 ====================


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    request=None,
) -> str:
    """验证 Bearer Token（JWT 或静态 API Token），白名单 IP 免认证"""
    from fastapi import Request

    # IP 白名单检查（通过 request 获取客户端 IP）
    # 注意: verify_token 作为 Depends 使用时 request 不会自动注入
    # 需要在具体路由使用时通过 Request 参数获取

    if credentials is not None:
        token = credentials.credentials

        # JWT
        payload = decode_jwt_token(token)
        if payload and payload.get("sub"):
            return payload["sub"]

        # 静态 API Token
        if hmac.compare_digest(token, get_api_token()):
            return "api"

    # 没有有效 token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def verify_token_or_whitelist(
    request: "Request",
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """验证 Token 或 IP 白名单，二者有一即可"""
    # 白名单 IP 直接放行（异步版，缓存过期时自动从 DB 刷新）
    client_ip = request.client.host if request.client else ""
    if await _check_ip_whitelist_async(client_ip):
        return "whitelist"

    # 走正常 token 验证
    return await verify_token(credentials)

