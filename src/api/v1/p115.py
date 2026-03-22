# app/api/v1/p115.py
# 115 网盘管理 API

import json as _json
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from src.core.security import verify_token
from src.core.timezone import tm
from src.db import get_async_session_local
from src.db.models.system import SystemConfig
from src.services.p115_service import P115Service

router = APIRouter(prefix="/p115", tags=["115 网盘"])
_p115_service = P115Service()

# systemconfig 中 115 配置的 key
_PATH_MAPPING_KEY = "p115_path_mapping"
_P115_SETTINGS_KEY = "p115_settings"


class CookiePayload(BaseModel):
    cookie: str


class QrcodeStartPayload(BaseModel):
    app: str = "web"   # 客户端类型: web, android, ios, alipaymini, wechatmini, tv 等


class QrcodeStep2Payload(BaseModel):
    uid: str
    time: str
    sign: str
    app: str = "web"


class SyncPayload(BaseModel):
    cid: str = "0"
    path: str = "/"


class OrganizePayload(BaseModel):
    file_ids: list[str]


@router.get("/status", dependencies=[Depends(verify_token)])
async def get_status():
    """获取 115 模块状态"""
    return await _p115_service.get_status()


@router.get("/account", dependencies=[Depends(verify_token)])
async def get_account_info():
    """获取 115 账号信息（用户名、头像、存储空间）"""
    return await _p115_service.get_account_info()


@router.post("/auth/cookie", dependencies=[Depends(verify_token)])
async def set_cookie(payload: CookiePayload):
    """设置 115 Cookie"""
    return await _p115_service.set_cookie(payload.cookie)


@router.get("/auth/qrcode/apps", dependencies=[Depends(verify_token)])
async def get_qrcode_apps():
    """获取支持的扫码客户端类型列表"""
    from src.adapters.storage.p115.p115_auth import P115AuthService
    return {"apps": P115AuthService.ALLOWED_APP_TYPES}


@router.post("/auth/qrcode/start", dependencies=[Depends(verify_token)])
async def qrcode_start(payload: QrcodeStartPayload = QrcodeStartPayload()):
    """115 扫码登录 — 获取二维码（支持选择客户端类型）"""
    return await _p115_service.qrcode_step1(app=payload.app)


@router.post("/auth/qrcode/poll", dependencies=[Depends(verify_token)])
async def qrcode_poll(payload: QrcodeStep2Payload):
    """115 扫码登录 — 轮询扫码状态"""
    return await _p115_service.qrcode_step2(
        payload.uid, payload.time, payload.sign, app=payload.app
    )


@router.get("/files", dependencies=[Depends(verify_token)])
async def browse_files(cid: str = "0", page: int = 1, size: int = 50):
    """浏览 115 目录（从本地缓存）"""
    return await _p115_service.browse_files(cid, page, size)


@router.post("/sync", dependencies=[Depends(verify_token)])
async def sync_directory(payload: SyncPayload):
    """同步 115 目录树到本地缓存"""
    return await _p115_service.sync_directory(payload.cid, payload.path)


@router.get("/download-url", dependencies=[Depends(verify_token)])
async def get_download_url(pick_code: str):
    """获取 115 直链"""
    return await _p115_service.get_download_url(pick_code)


@router.post("/organize", dependencies=[Depends(verify_token)])
async def organize_files(payload: OrganizePayload):
    """115 文件整理"""
    return await _p115_service.organize_files(payload.file_ids)


# ──────────────────── 路径映射（单条，存 systemconfig） ────────────────────

class PathMappingPayload(BaseModel):
    """路径映射配置：媒体库路径 / 网盘路径 / STRM路径 / 本地媒体路径 / 整理目录"""
    media_prefix: str = ""            # 媒体库中的路径前缀（Emby 看到的路径）
    cloud_prefix: str = ""            # 115 网盘中的路径前缀
    strm_prefix: str = ""             # STRM 文件输出目录路径前缀
    local_media_prefix: str = ""      # 本地媒体路径（用于 302 直链匹配）
    local_media_source: str = "local" # 来源: "local" 或存储源 ID
    organize_source: str = ""         # 网盘待整理目录
    organize_unrecognized: str = ""   # 网盘未识别目录（无法匹配分类时移入此处）


@router.get("/path-mapping", dependencies=[Depends(verify_token)])
async def get_path_mapping():
    """获取路径映射配置"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _PATH_MAPPING_KEY)
        )
        cfg = result.scalars().first()
        if cfg and cfg.value:
            try:
                return _json.loads(cfg.value)
            except (ValueError, TypeError):
                pass
    return {"media_prefix": "", "cloud_prefix": "", "strm_prefix": "", "local_media_prefix": "", "local_media_source": "local", "organize_source": "", "organize_unrecognized": ""}


@router.post("/path-mapping", dependencies=[Depends(verify_token)])
async def save_path_mapping(payload: PathMappingPayload):
    """保存路径映射配置"""
    value = _json.dumps(payload.model_dump(), ensure_ascii=False)
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _PATH_MAPPING_KEY)
        )
        cfg = result.scalars().first()
        if cfg:
            cfg.value = value
            cfg.updated_at = tm.now()
        else:
            cfg = SystemConfig(
                key=_PATH_MAPPING_KEY,
                value=value,
                description="115 路径映射（媒体库/网盘/STRM）",
                updated_at=tm.now(),
            )
            db.add(cfg)
        await db.commit()
    return {"success": True}



# ──────────────────── 115 高级设置（存 systemconfig） ────────────────────

_P115_SETTINGS_DEFAULTS = {
    "api_interval": 1,           # API 请求间隔 (秒)
    "api_concurrent": 3,         # API 并发线程数
    "strm_link_host": "",        # STRM 链接地址（302 反代地址）
    "file_extensions": "mp4,mkv,avi,ts,iso,mov,m2ts",  # 需要处理的扩展名
}


class P115SettingsPayload(BaseModel):
    api_interval: float = 1
    api_concurrent: int = 3
    strm_link_host: str = ""
    file_extensions: str = "mp4,mkv,avi,ts,iso,mov,m2ts"


@router.get("/settings", dependencies=[Depends(verify_token)])
async def get_p115_settings():
    """获取 115 高级设置"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _P115_SETTINGS_KEY)
        )
        cfg = result.scalars().first()
        if cfg and cfg.value:
            try:
                saved = _json.loads(cfg.value)
                # 用默认值补齐缺失字段
                return {**_P115_SETTINGS_DEFAULTS, **saved}
            except (ValueError, TypeError):
                pass
    return {**_P115_SETTINGS_DEFAULTS}


@router.post("/settings", dependencies=[Depends(verify_token)])
async def save_p115_settings(payload: P115SettingsPayload):
    """保存 115 高级设置"""
    value = _json.dumps(payload.model_dump(), ensure_ascii=False)
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _P115_SETTINGS_KEY)
        )
        cfg = result.scalars().first()
        if cfg:
            cfg.value = value
            cfg.updated_at = tm.now()
        else:
            cfg = SystemConfig(
                key=_P115_SETTINGS_KEY,
                value=value,
                description="115 高级设置",
                updated_at=tm.now(),
            )
            db.add(cfg)
        await db.commit()
    return {"success": True}


# ──────────────────── 115 目录树浏览（仅目录） ────────────────────

@router.get("/dir-tree", dependencies=[Depends(verify_token)])
async def browse_dir_tree(cid: str = "0"):
    """浏览 115 目录树 — 只返回文件夹，用于路径选择器"""
    return await _p115_service.browse_dir_tree(cid)
