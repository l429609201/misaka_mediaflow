# app/adapters/storage/p115/p115_adapter.py
# 115 存储适配器 — 实现 StorageAdapter 接口

import logging

import httpx

from src.adapters.storage.base import StorageAdapter, DirectLink, FileEntry
from src.adapters.storage.p115.p115_rate import P115RateLimiter
from src.adapters.storage.p115.p115_auth import P115AuthService
from src.adapters.storage.p115.p115_cache import P115IdPathCache

logger = logging.getLogger(__name__)

# 115 文件 API
_115_DOWNLOAD_URL = "https://proapi.115.com/app/chrome/downurl"
_115_FILES_URL = "https://webapi.115.com/files"
_115_SEARCH_URL = "https://webapi.115.com/files/search"
_115_SPACE_URL = "https://webapi.115.com/files/index_info"
_115_USER_URL = "https://my.115.com/?ct=ajax&ac=nav"


class P115StorageAdapter(StorageAdapter):
    """115 网盘存储适配器"""

    # 115 认证通过系统设置页（Cookie 扫码）完成，无需在存储管理页配置
    CONFIG_FIELDS = []

    def __init__(
        self,
        auth: P115AuthService,
        rate_limiter: P115RateLimiter,
        id_path_cache: P115IdPathCache,
    ):
        self._auth = auth
        self._rate = rate_limiter
        self._cache = id_path_cache
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def get_direct_link(self, cloud_path: str, **kwargs) -> DirectLink:
        """
        获取 115 CDN 直链
        kwargs 支持:
          - pick_code: str  直接传入 pick_code 跳过路径查找
          - sha1: str       文件 SHA1
        """
        pick_code = kwargs.get("pick_code", "")
        if not pick_code:
            # 通过路径从 ID/Path 缓存反查 pick_code
            # 生产环境中应查询 p115fscache 数据表
            file_id = self._cache.get_id(cloud_path)
            if not file_id:
                logger.warning("115 路径无法解析 pick_code: %s", cloud_path)
                return DirectLink()
            # file_id 场景下 pick_code 需从数据库取，此处做保护
            logger.warning("115 通过路径反查 pick_code 需数据库支持: %s", cloud_path)
            return DirectLink()

        await self._rate.acquire()
        client = await self._ensure_client()

        try:
            resp = await client.post(
                _115_DOWNLOAD_URL,
                data={"pickcode": pick_code},
                headers=self._auth.get_cookie_headers(),
            )
            data = resp.json()

            if not data.get("state"):
                err_msg = data.get("msg", data.get("error", "unknown"))
                # WAF 封禁检测
                if resp.status_code == 403 or "频" in str(err_msg):
                    self._rate.trigger_waf_cooldown()
                logger.error("115 直链获取失败: %s (pick_code=%s)", err_msg, pick_code)
                return DirectLink()

            # 解析直链 — data 格式: {"state": true, "data": {"<fid>": {"url": {"url": "..."}}}}
            file_data = data.get("data", {})
            for fid, info in file_data.items():
                url_info = info.get("url", {})
                if isinstance(url_info, dict):
                    download_url = url_info.get("url", "")
                elif isinstance(url_info, str):
                    download_url = url_info
                else:
                    download_url = ""

                if download_url:
                    return DirectLink(
                        url=download_url,
                        file_name=info.get("file_name", ""),
                        file_size=int(info.get("file_size", 0)),
                        expires_in=7200,
                        headers={"User-Agent": self._auth.get_cookie_headers()["User-Agent"]},
                    )

            logger.warning("115 直链响应中无有效 URL: pick_code=%s", pick_code)
            return DirectLink()

        except Exception as e:
            logger.error("115 直链请求异常: %s", e)
            return DirectLink()

    async def list_files(self, cloud_path: str, cid: str = "0") -> list[FileEntry]:
        """列出 115 目录内容"""
        await self._rate.acquire()
        client = await self._ensure_client()

        try:
            resp = await client.get(
                _115_FILES_URL,
                params={
                    "cid": cid,
                    "limit": 1000,
                    "show_dir": 1,
                    "o": "user_ptime",
                    "asc": 0,
                    "snap": 0,
                    "natsort": 1,
                    "source": "",
                    "format": "json",
                },
                headers=self._auth.get_cookie_headers(),
            )
            data = resp.json()
            if not data.get("state", True):
                logger.error("115 目录列表失败: %s", data.get("error", ""))
                return []

            entries: list[FileEntry] = []
            for item in data.get("data", []):
                is_dir = "fid" not in item
                entry = FileEntry(
                    name=item.get("n", ""),
                    path=f"{cloud_path}/{item.get('n', '')}".replace("//", "/"),
                    size=int(item.get("s", 0)) if not is_dir else 0,
                    is_dir=is_dir,
                    file_id=item.get("fid", item.get("cid", "")),
                    pick_code=item.get("pc", ""),
                    sha1=item.get("sha", ""),
                    ed2k=item.get("ed2k", ""),
                    mtime=item.get("te", ""),
                    ctime=item.get("tp", ""),
                )
                entries.append(entry)

                # 写入 ID/Path 缓存
                if entry.file_id:
                    self._cache.put(entry.file_id, entry.path)

            return entries

        except Exception as e:
            logger.error("115 目录列表异常: %s", e)
            return []

    async def test_connection(self) -> bool:
        """测试 115 连接"""
        if not self._auth.has_cookie:
            return False
        return await self._auth.verify_cookie()

    # 115 mark1 → VIP 等级映射
    # mark1 是位掩码，常见值:
    #   0       = 非 VIP
    #   1       = 普通 VIP
    #   11      = 年费 VIP
    #   127     = 铂金 VIP
    #   1048575 = 永久 VIP (0xFFFFF, 所有位全开)
    _VIP_MAP = {
        0:       ("", ""),
        1:       ("VIP", "blue"),
        11:      ("年费VIP", "gold"),
        127:     ("铂金VIP", "orange"),
        1048575: ("永久VIP", "volcano"),
    }

    @classmethod
    def _resolve_vip(cls, mark1: int) -> tuple[str, str]:
        """根据 mark1 值解析 VIP 等级名称和颜色"""
        if mark1 in cls._VIP_MAP:
            return cls._VIP_MAP[mark1]
        # 兜底: mark1 > 127 大概率是高级会员
        if mark1 > 127:
            return ("永久VIP", "volcano")
        if mark1 > 0:
            return ("VIP", "blue")
        return ("", "")

    async def get_user_info(self) -> dict:
        """获取 115 用户信息（头像、用户名、VIP 等级）"""
        if not self._auth.has_cookie:
            return {}
        try:
            client = await self._ensure_client()
            resp = await client.get(
                _115_USER_URL,
                headers=self._auth.get_cookie_headers(),
            )
            body = resp.json()
            # 115 nav 接口直接在顶层返回 user_name / face 等字段
            # 某些情况下可能嵌套在 data 里，需兼容两种结构
            data = body if isinstance(body, dict) else {}
            if "data" in data and isinstance(data["data"], dict):
                data = data["data"]
            logger.debug("115 nav 接口返回字段: %s", list(data.keys()))
            face = data.get("face", "")
            if isinstance(face, dict):
                face = face.get("face_l", "") or face.get("face_m", "")

            # ---- VIP 等级 ----
            mark1 = 0
            for key in ("mark1", "mark", "vip"):
                val = data.get(key)
                if isinstance(val, (int, float)) and val > 0:
                    mark1 = int(val)
                    break

            vip_name, vip_color = self._resolve_vip(mark1)
            # 如果接口直接返回了 vip_name，优先用它
            if data.get("vip_name"):
                vip_name = data["vip_name"]

            return {
                "user_name": data.get("user_name", ""),
                "face": face,
                "user_id": str(data.get("user_id", "")),
                "vip": mark1,
                "vip_name": vip_name,
                "vip_color": vip_color,
            }
        except Exception as e:
            logger.error("115 用户信息查询异常: %s", e)
            return {}

    async def get_space_usage(self) -> dict:
        """获取 115 空间用量"""
        if not self._auth.has_cookie:
            return {"total": 0, "used": 0, "free": 0}
        try:
            client = await self._ensure_client()
            resp = await client.get(
                _115_SPACE_URL,
                headers=self._auth.get_cookie_headers(),
            )
            body = resp.json()
            if not isinstance(body, dict):
                return {"total": 0, "used": 0, "free": 0}
            data = body.get("data", {})
            if not isinstance(data, dict):
                return {"total": 0, "used": 0, "free": 0}
            space = data.get("space_info", {})
            if not isinstance(space, dict):
                return {"total": 0, "used": 0, "free": 0}
            all_total = space.get("all_total", {})
            all_use = space.get("all_use", {})
            total = int(all_total.get("size", 0)) if isinstance(all_total, dict) else 0
            used = int(all_use.get("size", 0)) if isinstance(all_use, dict) else 0
            return {"total": total, "used": used, "free": total - used}
        except Exception as e:
            logger.error("115 空间用量查询异常: %s", e)
            return {"total": 0, "used": 0, "free": 0}

    async def get_download_url(self, pick_code: str) -> DirectLink:
        """通过 pick_code 直接获取直链（供 Go 内部 API 调用）"""
        return await self.get_direct_link("", pick_code=pick_code)

    async def search_file_by_cloud_path(self, cloud_path: str) -> str:
        """
        通过云端路径搜索文件，返回 pick_code（FsCache 无数据时的兜底方案）。

        原理：
          - 用文件名调用 115 搜索 API（webapi.115.com/files/search）
          - 遍历结果，用文件名精确匹配（n 字段 == filename）
          - 找到后返回 pick_code（pc 字段）

        参考：gostrm 参考项目 handle115PanDirectLink 的 pathCache 逻辑
        """
        from pathlib import Path as _Path
        filename = _Path(cloud_path).name
        if not filename:
            logger.warning("[p115] search_file_by_cloud_path: cloud_path 无文件名 '%s'", cloud_path)
            return ""

        await self._rate.acquire()
        client = await self._ensure_client()

        try:
            resp = await client.get(
                _115_SEARCH_URL,
                params={
                    "search_value": filename,
                    "limit": 20,
                    "offset": 0,
                    "format": "json",
                    "type": 99,   # 99 = 仅文件（不含目录）
                },
                headers=self._auth.get_cookie_headers(),
            )
            data = resp.json()

            if not data.get("state", True) and data.get("errno"):
                logger.error("[p115] 搜索 API 返回错误: %s", data.get("error", data))
                return ""

            items = data.get("data", [])
            if not items:
                logger.info("[p115] 搜索无结果: filename=%s cloud_path=%s", filename, cloud_path)
                return ""

            # 精确匹配文件名，取第一个命中
            for item in items:
                name = item.get("n", "")
                pc = item.get("pc", "")
                if name == filename and pc:
                    logger.info(
                        "[p115] 搜索命中: filename=%s → pickcode=%s (cloud_path=%s)",
                        filename, pc, cloud_path,
                    )
                    return pc

            logger.info(
                "[p115] 搜索结果中无精确匹配: filename=%s cloud_path=%s (共%d条结果)",
                filename, cloud_path, len(items),
            )
            return ""

        except Exception as e:
            logger.error("[p115] search_file_by_cloud_path 异常: %s (cloud_path=%s)", e, cloud_path)
            return ""

