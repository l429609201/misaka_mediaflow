# app/adapters/storage/p115/p115_auth.py
# 115 认证管理 — Cookie / OpenAPI Token / 扫码登录

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 115 API 端点
_115_QRCODE_TOKEN_URL = "https://qrcodeapi.115.com/api/1.0/web/1.0/token"
_115_QRCODE_STATUS_URL = "https://qrcodeapi.115.com/get/status/"
_115_QRCODE_LOGIN_URL = "https://passportapi.115.com/app/1.0/web/1.0/login/qrcode"
_115_OPENAPI_TOKEN_URL = "https://open.115.com/auth/token"


class P115AuthService:
    """115 认证服务"""

    def __init__(self):
        self._cookie: str = ""
        self._login_app: str = "web"   # 记录扫码时选择的 app 类型，决定 CK 的 SSOENT
        self._openapi_access_token: str = ""
        self._openapi_refresh_token: str = ""
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    # ==================== Cookie 管理 ====================

    def set_cookie(self, cookie: str):
        """设置 115 Cookie"""
        self._cookie = cookie.strip()
        logger.info("115 Cookie 已更新 (len=%d)", len(self._cookie))

    @property
    def cookie(self) -> str:
        return self._cookie

    @property
    def login_app(self) -> str:
        """返回扫码登录时选择的 app 类型（决定 CK 的 SSOENT 类型）"""
        return self._login_app

    @property
    def has_cookie(self) -> bool:
        return bool(self._cookie)

    def get_cookie_headers(self) -> dict:
        """返回带 Cookie 的请求头"""
        return {
            "Cookie": self._cookie,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }

    # ==================== OpenAPI Token 管理 ====================

    def set_openapi_tokens(self, access_token: str, refresh_token: str):
        """设置 OpenAPI Token"""
        self._openapi_access_token = access_token
        self._openapi_refresh_token = refresh_token
        logger.info("115 OpenAPI Token 已更新")

    @property
    def openapi_access_token(self) -> str:
        return self._openapi_access_token

    @property
    def openapi_refresh_token(self) -> str:
        return self._openapi_refresh_token

    @property
    def has_openapi(self) -> bool:
        return bool(self._openapi_access_token)

    def get_openapi_headers(self) -> dict:
        """返回带 OpenAPI Token 的请求头"""
        return {"Authorization": f"Bearer {self._openapi_access_token}"}

    async def refresh_openapi_token(self) -> bool:
        """刷新 OpenAPI Access Token"""
        if not self._openapi_refresh_token:
            logger.warning("无 refresh_token，无法刷新")
            return False
        try:
            client = await self._ensure_client()
            resp = await client.post(_115_OPENAPI_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": self._openapi_refresh_token,
            })
            data = resp.json()
            if "access_token" in data:
                self._openapi_access_token = data["access_token"]
                if "refresh_token" in data:
                    self._openapi_refresh_token = data["refresh_token"]
                logger.info("115 OpenAPI Token 刷新成功")
                return True
            logger.error("115 OpenAPI Token 刷新失败: %s", data)
            return False
        except Exception as e:
            logger.error("115 OpenAPI Token 刷新异常: %s", e)
            return False

    # ==================== 扫码登录 ====================

    # 115 支持的客户端类型（不同 app 类型获取的 Cookie 适用范围不同）
    ALLOWED_APP_TYPES = [
        "web",          # 网页版
        "android",      # 安卓
        "115android",   # 115安卓
        "ios",          # iOS
        "115ios",       # 115 iOS
        "alipaymini",   # 支付宝小程序（推荐，稳定）
        "wechatmini",   # 微信小程序
        "115ipad",      # 115 iPad
        "tv",           # TV 版
        "qandroid",     # 轻量安卓
    ]

    async def qrcode_login_step1(self, app: str = "web") -> Optional[dict]:
        """
        扫码登录第1步 — 获取二维码 Token 和图片
        :param app: 客户端类型, 默认 web
        :return: {uid, time, sign, qrcode_url, app}
        """
        if app not in self.ALLOWED_APP_TYPES:
            app = "web"
        try:
            client = await self._ensure_client()
            resp = await client.get(_115_QRCODE_TOKEN_URL, params={"app": app})
            data = resp.json()
            if data.get("state"):
                qr_data = data.get("data", {})
                uid = qr_data.get("uid", "")
                # 115 API 返回的 qrcode 字段就是二维码内容字符串，前端用 QRCode 组件渲染
                qrcode_content = qr_data.get("qrcode", "")
                logger.info("获取 115 二维码成功, uid=%s, app=%s", uid, app)
                return {
                    "uid": uid,
                    "time": str(qr_data.get("time", "")),
                    "sign": str(qr_data.get("sign", "")),
                    "qrcode_content": qrcode_content,
                    "app": app,
                }
            logger.error("获取二维码 Token 失败: %s", data)
            return None
        except Exception as e:
            logger.error("获取二维码异常: %s", e)
            return None

    async def qrcode_login_step2(
        self, uid: str, time_val: str, sign: str, app: str = "web"
    ) -> dict:
        """
        扫码登录第2步 — 轮询状态
        :return: {status: "waiting"|"scanned"|"success"|"expired"|"canceled", cookie?: str}
        """
        if app not in self.ALLOWED_APP_TYPES:
            app = "web"
        try:
            client = await self._ensure_client()
            resp = await client.get(
                _115_QRCODE_STATUS_URL,
                params={"uid": uid, "time": time_val, "sign": sign},
            )
            data = resp.json()
            status_code = data.get("data", {}).get("status", -1)

            if status_code == 0:
                return {"status": "waiting"}
            elif status_code == 1:
                return {"status": "scanned"}
            elif status_code == 2:
                cookie = await self._exchange_cookie(uid, app)
                if cookie:
                    return {"status": "success", "cookie": cookie}
                return {"status": "error", "error": "换取 Cookie 失败"}
            elif status_code == -1:
                return {"status": "expired"}
            elif status_code == -2:
                return {"status": "canceled"}
            else:
                return {"status": "waiting"}
        except httpx.TimeoutException:
            # 轮询超时是正常的（等待用户扫码），静默返回 waiting
            logger.debug("二维码状态轮询超时 uid=%s", uid)
            return {"status": "waiting"}
        except Exception as e:
            logger.warning("二维码状态查询异常: %s(%s)", type(e).__name__, e or "no detail")
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    async def _exchange_cookie(self, uid: str, app: str = "web") -> Optional[str]:
        """用扫码 UID 换取 Cookie（根据 app 类型获取不同端的 Cookie）"""
        try:
            client = await self._ensure_client()
            resp = await client.post(
                _115_QRCODE_LOGIN_URL,
                data={"account": uid, "app": app},
            )
            data = resp.json()
            if data.get("state"):
                cookie_data = data.get("data", {}).get("cookie", {})
                cookie_parts = [f"{k}={v}" for k, v in cookie_data.items() if k and v]
                cookie_str = "; ".join(cookie_parts)
                self.set_cookie(cookie_str)
                self._login_app = app   # 记录本次登录的 app 类型，供生活事件监控等使用
                logger.info("115 扫码登录成功, app=%s, cookie_len=%d", app, len(cookie_str))
                return cookie_str
            logger.error("换取 Cookie 失败: %s", data)
            return None
        except Exception as e:
            logger.error("换取 Cookie 异常: %s", e)
            return None

    # ==================== 验证 ====================

    async def verify_cookie(self) -> bool:
        """验证当前 Cookie 是否有效"""
        if not self.has_cookie:
            return False
        try:
            client = await self._ensure_client()
            resp = await client.get(
                "https://my.115.com/?ct=ajax&ac=nav",
                headers=self.get_cookie_headers(),
            )
            data = resp.json()
            return data.get("state", False)
        except Exception:
            return False