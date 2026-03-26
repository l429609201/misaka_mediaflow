# app/adapters/storage/p115/p115_auth.py
# 115 认证管理 — Cookie / OpenAPI Token / 扫码登录
#
#   使用 p115client.P115Client 的静态方法代替手动拼 URL，
#   确保 login_qrcode_scan_result 的 URL 路径中 app 类型正确动态拼接。

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 115 API 端点（仅 OpenAPI 仍用手动请求）
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
        注意：_exchange_cookie 不应在 set_cookie 之后再覆写 _login_app，
        因为 115 服务端可能为某些 app（如 alipaymini）返回 web 类型 CK（SSOENT=A1），
        SSOENT 识别结果才是真正决定 API 路径的依据。
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
        扫码登录第1步 — 获取二维码 Token 和图片。
        P115Client 的静态方法是同步阻塞 IO，必须用 asyncio.to_thread 包裹，
        否则会阻塞 FastAPI 事件循环导致整个服务卡死。
        """
        import asyncio
        from base64 import b64encode

        if app not in self.ALLOWED_APP_TYPES:
            app = "web"
        try:
            from p115client import P115Client, check_response

            # 1. 获取二维码 Token（uid, time, sign）—— 同步网络 IO，放进线程池
            resp = await asyncio.to_thread(P115Client.login_qrcode_token)
            check_response(resp)
            qr_data = resp.get("data", {})
            uid   = str(qr_data.get("uid",  ""))
            _time = str(qr_data.get("time", ""))
            _sign = str(qr_data.get("sign", ""))

            # 2. 获取二维码图片 bytes —— 同样是同步 IO
            qr_bytes = await asyncio.to_thread(P115Client.login_qrcode, uid)
            qrcode_base64 = b64encode(qr_bytes).decode("utf-8")

            logger.info("获取 115 二维码成功 (P115Client), uid=%s, app=%s", uid, app)
            return {
                "uid": uid,
                "time": _time,
                "sign": _sign,
                "qrcode_content": f"data:image/png;base64,{qrcode_base64}",
                "app": app,
            }
        except Exception as e:
            logger.error("获取二维码异常 (P115Client): %s", e, exc_info=True)
            return None

    async def qrcode_login_step2(
        self, uid: str, time_val: str, sign: str, app: str = "web"
    ) -> dict:
        """
        扫码登录第2步 — 轮询状态。
        P115Client.login_qrcode_scan_status 是同步阻塞 IO，用 asyncio.to_thread 包裹。

        :return: {status: "waiting"|"scanned"|"success"|"expired"|"canceled", cookie?: str}
        """
        if app not in self.ALLOWED_APP_TYPES:
            app = "web"
        try:
            import asyncio
            from p115client import P115Client

            payload = {"uid": uid, "time": time_val, "sign": sign}
            # 同步网络 IO → 放进线程池，不阻塞事件循环
            resp = await asyncio.to_thread(P115Client.login_qrcode_scan_status, payload)
            # 注意：不调用 check_response()，因为 status=1(已扫码) 时
            # 115 返回的 state 字段为 False，check_response 会误判为失败并抛异常。
            status_code = resp.get("data", {}).get("status")

            if status_code == 0:
                return {"status": "waiting"}
            elif status_code == 1:
                return {"status": "scanned"}
            elif status_code == 2:
                cookie = await self._exchange_cookie(uid, app)
                if cookie:
                    return {"status": "success", "cookie": cookie}
                return {"status": "error", "error": "换取 Cookie 失败"}
            elif status_code == -1 or (
                status_code is None and resp.get("message") == "key invalid"
            ):
                return {"status": "expired"}
            elif status_code == -2:
                return {"status": "canceled"}
            else:
                return {"status": "waiting"}
        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str or "timed out" in err_str:
                logger.debug("二维码状态轮询超时 uid=%s", uid)
                return {"status": "waiting"}
            logger.warning("二维码状态查询异常: %s(%s)", type(e).__name__, e or "no detail")
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    async def _exchange_cookie(self, uid: str, app: str = "web") -> Optional[str]:
        """
        用扫码 UID 换取 Cookie。
        使用 P115Client.login_qrcode_scan_result(uid, app=app)。

        关键修复：
          之前硬编码 URL = passportapi.115.com/app/1.0/web/1.0/login/qrcode
          P115Client 会动态拼接 → passportapi.115.com/app/1.0/{app}/1.0/login/qrcode/
          确保 alipaymini/android 等 app 类型换取到正确 SSOENT 的 Cookie。
        """
        try:
            import asyncio
            from p115client import P115Client, check_response

            # 同步网络 IO → 放进线程池，不阻塞事件循环
            resp = await asyncio.to_thread(P115Client.login_qrcode_scan_result, uid, app)
            check_response(resp)

            if resp.get("state") and resp.get("data"):
                cookie_data = resp.get("data", {})
                cookie_string = ""
                if "cookie" in cookie_data and isinstance(cookie_data["cookie"], dict):
                    cookie_string = "; ".join(
                        f"{name}={value}"
                        for name, value in cookie_data["cookie"].items()
                        if name and value
                    )

                if cookie_string:
                    self.set_cookie(cookie_string)
                    # 不在此覆写 _login_app：set_cookie() 已通过 SSOENT 识别出真实 login_app。
                    logger.info(
                        "115 扫码登录成功 (P115Client), scan_app=%s, effective_login_app=%s, cookie_len=%d",
                        app, self._login_app, len(cookie_string),
                    )
                    return cookie_string

                logger.error("换取 Cookie 成功但解析为空: %s", cookie_data)
                return None
            else:
                specific_error = resp.get("message", resp.get("error", "未知错误"))
                logger.error("换取 Cookie 失败: %s", specific_error)
                return None
        except Exception as e:
            logger.error("换取 Cookie 异常 (P115Client): %s", e, exc_info=True)
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