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

    # SSOENT → app 映射，来源于 p115client/const.py APP_TO_SSOENT 的反转
    # 格式：SSOENT值（如"A1"）→ app名（如"web"）
    _SSOENT_TO_APP: dict[str, str] = {
        "A1": "web",        # 115生活_网页端
        "D1": "ios",        # 115生活_苹果端
        "D2": "ios",        # bios（降级到 ios）
        "D3": "115ios",     # 115_苹果端
        "F1": "android",    # 115生活_安卓端
        "F2": "android",    # bandroid（降级到 android）
        "F3": "115android", # 115_安卓端
        "H1": "ipad",       # 115生活_苹果平板端
        "H2": "ipad",       # bipad（降级到 ipad）
        "H3": "115ipad",    # 115_苹果平板端
        "I1": "tv",         # 115生活_安卓电视端
        "I2": "apple_tv",   # 115生活_苹果电视端
        "M1": "qandroid",   # 115管理_安卓端
        "N1": "qios",       # 115管理_苹果端
        "O1": "qipad",      # 115管理_苹果平板端
        "P1": "os_windows", # 115生活_Windows端
        "P2": "os_mac",     # 115生活_macOS端
        "P3": "os_linux",   # 115生活_Linux端
        "R1": "wechatmini", # 115生活_微信小程序端
        "R2": "alipaymini", # 115生活_支付宝小程序
        "S1": "harmony",    # 115_鸿蒙端
    }

    @staticmethod
    def _detect_login_app(cookie: str) -> str:
        """
        从 cookie 字符串中解析 SSOENT 字段，推断对应的 login_app 类型。

        115 Cookie 中的 SSOENT 字段格式例如：SSOENT=A1 / SSOENT=F1 / SSOENT=D1
        通过此字段可以精确判断该 CK 属于哪种客户端类型，
        从而决定生活事件监控应使用哪个接口（life_list 还是 behavior_once）。

        :param cookie: cookie 字符串（键值对形式，分号分隔）
        :return: 推断出的 app 类型字符串，默认返回 "web"
        """
        import re
        m = re.search(r'(?:^|[\s;])SSOENT=([^\s;]+)', cookie)
        if not m:
            return "web"
        ssoent = m.group(1).strip()
        app = P115AuthService._SSOENT_TO_APP.get(ssoent, "")
        if app:
            return app
        # 未知 SSOENT 值，尝试按首字母推断大类
        # A→web, D→ios, F→android, H→ipad, I→tv, M/N/O→qandroid, P→os_windows, R→alipaymini, S→harmony
        _prefix_map = {
            "A": "web", "D": "ios", "F": "android", "H": "ipad",
            "I": "tv",  "M": "qandroid", "N": "qios", "O": "qipad",
            "P": "os_windows", "R": "alipaymini", "S": "harmony",
        }
        prefix = ssoent[0].upper() if ssoent else ""
        return _prefix_map.get(prefix, "web")

    def set_cookie(self, cookie: str):
        """
        设置 115 Cookie，并自动从 SSOENT 字段推断 login_app 类型。

        所有 Cookie 设置路径（手动粘贴、启动加载、扫码登录）都走这里，
        统一在此自动识别 CK 类型，无需用户手动指定。
        扫码登录成功后 _exchange_cookie 会在调用本方法后再覆写 _login_app，
        两者结果应当一致，覆写无害。
        """
        self._cookie = cookie.strip()
        detected = self._detect_login_app(self._cookie)
        self._login_app = detected
        logger.info(
            "115 Cookie 已更新 (len=%d, 识别login_app=%s)",
            len(self._cookie), detected,
        )

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

        说明：115 二维码状态接口响应通常在 1s 内完成。
        使用较短的 timeout=8s，避免每次轮询阻塞太久（全局 client timeout=30s 不适合轮询场景）。
        超时视为 waiting 返回，让前端继续轮询；
        前端需自行设置最大轮询次数兜底（防止二维码过期后永远轮询）。
        """
        if app not in self.ALLOWED_APP_TYPES:
            app = "web"
        try:
            client = await self._ensure_client()
            resp = await client.get(
                _115_QRCODE_STATUS_URL,
                params={"uid": uid, "time": time_val, "sign": sign},
                timeout=8,  # 状态接口应快速响应，短 timeout 避免长时间阻塞
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
            # 轮询超时：等待用户扫码期间偶发正常，静默返回 waiting
            # 前端有最大轮询次数兜底（约5分钟），超出后自动标记 expired
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