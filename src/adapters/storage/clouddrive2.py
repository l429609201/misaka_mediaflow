# app/adapters/storage/clouddrive2.py
# CloudDrive2 存储适配器 — 使用官方 gRPC 客户端库 clouddrive2-client
#
# CloudDrive2 暴露的是纯 gRPC 接口，没有任何 REST/HTTP 端点。
# 官方 Python 客户端：pip install clouddrive2-client
#
# 认证优先级（二选一）：
#   1. API Token（推荐）：在 CD2 管理后台「令牌管理」生成，填入 token 字段。
#      库内部 jwt_token 为公开属性，直接赋值即可跳过用户名密码登录。
#   2. 用户名 + 密码：调用 authenticate() 获取 JWT，自动存入 jwt_token。
#
# 客户端所有方法均为同步，用 asyncio.to_thread 包装为异步。

import asyncio
import logging
from urllib.parse import urlparse

from src.adapters.storage.base import StorageAdapter, DirectLink, FileEntry, FieldSpec

logger = logging.getLogger(__name__)


def _parse_grpc_endpoint(host: str) -> str:
    """
    把用户填写的 host 字段转换成 gRPC endpoint（host:port）。
    兼容以下格式：
      - "192.168.10.7:19798"         → 原样返回
      - "http://192.168.10.7:19798"  → "192.168.10.7:19798"
      - "https://192.168.10.7:19798" → "192.168.10.7:19798"
    """
    host = host.strip().rstrip("/")
    if host.startswith(("http://", "https://")):
        parsed = urlparse(host)
        return parsed.netloc        # "192.168.10.7:19798"
    return host


class CloudDrive2Adapter(StorageAdapter):
    """CloudDrive2 存储适配器（gRPC）"""

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
            placeholder="请输入在 CD2 管理后台「令牌管理」生成的 Token",
            hint="在 CloudDrive2 管理后台 → 令牌管理 中生成，安全且无需暴露密码",
            show_when={"auth_mode": "token"},
        ),
        FieldSpec(
            key="username",
            label="用户名",
            type="text",
            placeholder="CloudDrive2 登录用户名",
            show_when={"auth_mode": "password"},
        ),
        FieldSpec(
            key="password",
            label="密码",
            type="password",
            secret=True,
            placeholder="CloudDrive2 登录密码",
            show_when={"auth_mode": "password"},
        ),
    ]

    def __init__(self, host: str, config: dict):
        self._endpoint = _parse_grpc_endpoint(host)
        self._api_token = config.get("token", "")
        self._username  = config.get("username", "")
        self._password  = config.get("password", "")
        self._grpc_client = None

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _get_client(self):
        """
        获取（并缓存）已认证的 gRPC 客户端（同步）。

        认证逻辑：
          - 若 token 非空 → 直接赋值 jwt_token，无需网络请求
          - 否则 → 调用 authenticate(username, password) 换取 JWT
        """
        if self._grpc_client is not None:
            return self._grpc_client
        try:
            from clouddrive2_client import CloudDriveClient
        except ImportError as exc:
            raise RuntimeError(
                "缺少依赖：请执行 pip install clouddrive2-client"
            ) from exc

        client = CloudDriveClient(self._endpoint)

        if self._api_token:
            # API Token 模式：jwt_token 是公开属性，直接赋值即可
            client.jwt_token = self._api_token
            logger.debug("CloudDrive2 使用 API Token 认证 endpoint=%s", self._endpoint)
        elif self._username:
            # 用户名+密码模式：调用 GetToken RPC 换取 JWT
            ok = client.authenticate(self._username, self._password or "")
            if ok:
                logger.debug("CloudDrive2 用户名密码认证成功 endpoint=%s", self._endpoint)
            else:
                logger.warning("CloudDrive2 用户名密码认证失败 endpoint=%s", self._endpoint)
        else:
            logger.warning("CloudDrive2 未提供任何认证凭据 endpoint=%s", self._endpoint)

        self._grpc_client = client
        return client

    async def _run(self, func, *args):
        """在线程池中执行同步 gRPC 调用，避免阻塞事件循环。"""
        return await asyncio.to_thread(func, *args)

    # ------------------------------------------------------------------
    # StorageAdapter 接口实现
    # ------------------------------------------------------------------

    async def get_direct_link(self, cloud_path: str, **kwargs) -> DirectLink:
        """
        通过 get_download_url(path) 获取 CloudDrive2 直链。
        返回的是一个包含 url（及可选 userAgent/headers）的对象。
        """
        try:
            client = self._get_client()
            result = await self._run(client.get_download_url, cloud_path)
            # result 是一个带 url 字段的对象，或者直接是字符串
            if isinstance(result, str):
                url = result
            else:
                url = getattr(result, "url", "") or getattr(result, "downloadUrl", "") or ""
            return DirectLink(url=url)
        except Exception as exc:
            logger.warning("CloudDrive2 get_direct_link 失败 path=%s: %s", cloud_path, exc)
            return DirectLink()

    async def list_files(self, cloud_path: str) -> list[FileEntry]:
        """列出目录下的文件和子目录。get_sub_files 返回 Iterator[CloudDriveFile]。"""
        try:
            client = self._get_client()
            sub_files = await self._run(client.get_sub_files, cloud_path)
        except Exception as exc:
            logger.warning("CloudDrive2 list_files 失败 path=%s: %s", cloud_path, exc)
            return []

        entries = []
        for f in sub_files or []:
            # CloudDriveFile 字段：name, fullPathName, isDirectory, size
            name = getattr(f, "name", "") or ""
            full_path = getattr(f, "fullPathName", "") or f"{cloud_path.rstrip('/')}/{name}"
            is_dir = bool(getattr(f, "isDirectory", False))
            size = int(getattr(f, "size", 0) or 0)
            entries.append(FileEntry(
                name=name,
                path=full_path,
                size=size,
                is_dir=is_dir,
            ))
        return entries

    async def test_connection(self) -> bool:
        """测试连接：调用 get_system_info 验证。"""
        try:
            client = self._get_client()
            info = await self._run(client.get_system_info)
            return info is not None
        except Exception as exc:
            logger.warning("CloudDrive2 test_connection 失败: %s", exc)
            return False

    async def get_space_usage(self) -> dict:
        """获取存储用量，使用 get_space_info('/')。"""
        try:
            client = self._get_client()
            space = await self._run(client.get_space_info, "/")
            # SpaceInfo 字段：totalSpace, usedSpace, freeSpace
            total = int(getattr(space, "totalSpace", 0) or 0)
            used = int(getattr(space, "usedSpace", 0) or 0)
            free = int(getattr(space, "freeSpace", 0) or 0)
            return {"total": total, "used": used, "free": free}
        except Exception as exc:
            logger.warning("CloudDrive2 get_space_usage 失败: %s", exc)
            return {"total": 0, "used": 0, "free": 0}

    def __del__(self):
        """释放 gRPC channel。"""
        if self._grpc_client is not None:
            try:
                self._grpc_client.close()
            except Exception:
                pass

