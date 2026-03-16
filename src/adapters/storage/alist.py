# app/adapters/storage/alist.py
# Alist 存储适配器

import logging
import httpx

from src.adapters.storage.base import StorageAdapter, DirectLink, FileEntry, FieldSpec

logger = logging.getLogger(__name__)


class AlistAdapter(StorageAdapter):
    """Alist 存储适配器"""

    CONFIG_FIELDS = [
        FieldSpec(
            key="auth_mode",
            label="认证方式",
            type="select",
            default="token",
            options=[
                {"value": "token", "label": "API Token（推荐）"},
                {"value": "password", "label": "用户名 + 密码"},
            ],
        ),
        FieldSpec(
            key="token",
            label="API Token",
            type="password",
            secret=True,
            placeholder="Alist 后台「个人资料」中生成的 Token",
            hint="在 Alist 管理页 → 个人资料 → Token 中获取",
            show_when={"auth_mode": "token"},
        ),
        FieldSpec(
            key="username",
            label="用户名",
            type="text",
            placeholder="Alist 登录用户名",
            show_when={"auth_mode": "password"},
        ),
        FieldSpec(
            key="password",
            label="密码",
            type="password",
            secret=True,
            placeholder="Alist 登录密码",
            show_when={"auth_mode": "password"},
        ),
    ]

    def __init__(self, host: str, config: dict):
        self._host     = host.rstrip("/")
        self._token    = config.get("token", "")
        self._username = config.get("username", "")
        self._password = config.get("password", "")
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._host, timeout=30)
            if self._username and self._password and not self._token:
                await self._login()
        return self._client

    async def _login(self):
        try:
            resp = await self._client.post("/api/auth/login", json={
                "username": self._username,
                "password": self._password,
            })
            resp.raise_for_status()
            data = resp.json()
            self._token = data.get("data", {}).get("token", "")
            logger.info("Alist 登录成功")
        except Exception as exc:
            logger.warning("Alist 登录失败: %s", exc)

    def _headers(self) -> dict:
        return {"Authorization": self._token} if self._token else {}

    async def get_direct_link(self, cloud_path: str, **kwargs) -> DirectLink:
        client = await self._ensure_client()
        resp = await client.post(
            "/api/fs/get",
            json={"path": cloud_path},
            headers=self._headers(),
        )
        data = resp.json().get("data", {})
        return DirectLink(
            url=data.get("raw_url", ""),
            file_name=data.get("name", ""),
            file_size=data.get("size", 0),
        )

    async def list_files(self, cloud_path: str) -> list[FileEntry]:
        client = await self._ensure_client()
        try:
            resp = await client.post(
                "/api/fs/list",
                json={"path": cloud_path, "refresh": False},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
        except Exception as exc:
            logger.warning("Alist list_files 失败 path=%s: %s", cloud_path, exc)
            return []
        entries = []
        for item in data.get("content", []) or []:
            entries.append(FileEntry(
                name=item.get("name", ""),
                path=f"{cloud_path.rstrip('/')}/{item.get('name', '')}",
                size=item.get("size", 0),
                is_dir=item.get("is_dir", False),
            ))
        return entries

    async def test_connection(self) -> bool:
        try:
            client = await self._ensure_client()
            resp = await client.get("/api/public/settings", headers=self._headers())
            return resp.status_code == 200
        except Exception:
            return False

    async def get_space_usage(self) -> dict:
        return {"total": 0, "used": 0, "free": 0}

