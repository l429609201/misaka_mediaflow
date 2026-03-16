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
    """获取 API Token，未配置则从数据库加载或自动生成并持久化"""
    global _runtime_api_token

    # 1. 配置文件优先
    if settings.security.api_token:
        return settings.security.api_token

    # 2. 内存缓存
    if _runtime_api_token is not None:
        return _runtime_api_token

    # 3. 从 systemconfig 表加载
    try:
        db = _get_sync_session()
        try:
            from src.db.models import SystemConfig
            cfg = db.query(SystemConfig).filter(SystemConfig.key == "api_token").first()
            if cfg and cfg.value:
                _runtime_api_token = cfg.value
                logger.info("API Token 已从数据库加载")
                return _runtime_api_token
        finally:
            db.close()
    except Exception:
        pass

    # 4. 随机生成并持久化
    _runtime_api_token = secrets.token_urlsafe(32)
    try:
        db = _get_sync_session()
        try:
            from src.db.models import SystemConfig
            from src.core.timezone import tm
            cfg = SystemConfig(
                key="api_token", value=_runtime_api_token,
                description="API Token / JWT Secret（自动生成）", updated_at=tm.now(),
            )
            db.add(cfg)
            db.commit()
            logger.info("API Token 已自动生成并持久化到数据库")
        finally:
            db.close()
    except Exception as e:
        logger.warning("API Token 持久化失败: %s", e)

    return _runtime_api_token


# ==================== 管理员密码管理（user 表） ====================

_initial_password: Optional[str] = None
_admin_password_hash: Optional[str] = None


def _get_sync_session():
    """获取同步数据库会话（延迟导入避免循环依赖）"""
    from src.db import database as db_module
    if db_module.SyncSessionLocal is None:
        raise RuntimeError("SyncSessionLocal not initialized yet")
    return db_module.SyncSessionLocal()


def initialize_admin_password():
    """
    初始化管理员密码：
    1. 配置文件 security.admin_password -> 优先（同步写入 user 表）
    2. user 表已有 admin -> 加载
    3. 都没有 -> 随机生成 -> 打印到控制台 + 写入 user 表
    """
    global _initial_password, _admin_password_hash

    # 1. 配置文件优先
    configured = getattr(settings.security, "admin_password", "")
    if configured:
        _admin_password_hash = hash_password(configured)
        try:
            db = _get_sync_session()
            try:
                from src.db.models import User
                from src.core.timezone import tm
                now = tm.now()
                user = db.query(User).filter(User.username == ADMIN_USERNAME).first()
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
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.debug("配置密码同步到 user 表失败: %s", e)
        logger.info("管理员密码已从配置加载")
        return

    # 2. 从 user 表读取
    try:
        db = _get_sync_session()
        try:
            from src.db.models import User
            user = db.query(User).filter(User.username == ADMIN_USERNAME).first()
            if user and user.password_hash:
                _admin_password_hash = user.password_hash
                logger.info("管理员密码已从 user 表加载")
                return
        finally:
            db.close()
    except Exception as e:
        logger.warning("数据库读取密码失败: %s", e)

    # 3. 随机生成
    _initial_password = secrets.token_urlsafe(12)
    _admin_password_hash = hash_password(_initial_password)

    print("\n" + "=" * 60)
    print("  Misaka MediaFlow 初始管理员账户")
    print(f"   用户名: {ADMIN_USERNAME}")
    print(f"   密码:   {_initial_password}")
    print("   请登录后在设置页面修改密码!")
    print("=" * 60 + "\n")
    logger.info("初始管理员密码已随机生成（详见控制台输出）")

    try:
        db = _get_sync_session()
        try:
            from src.db.models import User
            from src.core.timezone import tm
            now = tm.now()
            user = User(
                username=ADMIN_USERNAME,
                password_hash=_admin_password_hash,
                role="admin", is_active=1,
                created_at=now, updated_at=now,
            )
            db.add(user)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("密码写入 user 表失败: %s", e)


def get_admin_password_hash() -> str:
    global _admin_password_hash
    if _admin_password_hash is None:
        initialize_admin_password()
    return _admin_password_hash


def update_admin_password(new_password: str):
    """更新管理员密码（写入 user 表）"""
    global _admin_password_hash
    _admin_password_hash = hash_password(new_password)
    try:
        db = _get_sync_session()
        try:
            from src.db.models import User
            from src.core.timezone import tm
            now = tm.now()
            user = db.query(User).filter(User.username == ADMIN_USERNAME).first()
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
            db.commit()
            logger.info("管理员密码已更新")
        finally:
            db.close()
    except Exception as e:
        logger.error("密码更新失败: %s", e)


# ==================== IP 白名单（从数据库 systemconfig 表读取） ====================

# 内存缓存，避免每次请求都查数据库
_whitelist_cache: list = []
_whitelist_cache_ts: float = 0


def _load_whitelist_from_db() -> list:
    """从 systemconfig 表读取白名单"""
    import json as _json
    global _whitelist_cache, _whitelist_cache_ts
    import time as _time

    # 缓存 10 秒
    now = _time.time()
    if _whitelist_cache_ts and now - _whitelist_cache_ts < 10:
        return _whitelist_cache

    try:
        db = _get_sync_session()
        try:
            from src.db.models import SystemConfig
            cfg = db.query(SystemConfig).filter(SystemConfig.key == "ip_whitelist").first()
            if cfg and cfg.value:
                _whitelist_cache = _json.loads(cfg.value)
            else:
                _whitelist_cache = []
            _whitelist_cache_ts = now
        finally:
            db.close()
    except Exception:
        pass
    return _whitelist_cache


def invalidate_whitelist_cache():
    """清除白名单缓存（修改后调用）"""
    global _whitelist_cache_ts
    _whitelist_cache_ts = 0


def _check_ip_whitelist(client_ip: str) -> bool:
    """检查 IP 是否在白名单中（支持 CIDR 格式，兼容 IPv6 ::1 → 127.0.0.1）"""
    import ipaddress
    whitelist = _load_whitelist_from_db()
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
    # 白名单 IP 直接放行
    client_ip = request.client.host if request.client else ""
    if _check_ip_whitelist(client_ip):
        return "whitelist"

    # 走正常 token 验证
    return await verify_token(credentials)

