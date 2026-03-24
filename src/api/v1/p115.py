# app/api/v1/p115.py
# 115 网盘管理 API

import json as _json
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from src.core.security import verify_token
from src.core.timezone import tm
from src.db import get_async_session_local
from src.db.models.system import SystemConfig
from src.services.p115_service import P115Service

logger = logging.getLogger(__name__)
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


# ──────────────────── 刮削重命名配置 ────────────────────

_SCRAPE_CONFIG_KEY = "p115_scrape_config"

_SCRAPE_DEFAULTS = {
    "enabled": False,
    "movie_format":  "{title} ({year})/{title} ({year})",
    "tv_format":     "{title} ({year})/Season {season:02d}/{title} - {season_episode} - {episode_title}",
}


class ScrapeConfigPayload(BaseModel):
    enabled: bool = False
    movie_format: str = "{title} ({year})/{title} ({year})"
    tv_format:    str = "{title} ({year})/Season {season:02d}/{title} - {season_episode} - {episode_title}"


@router.get("/scrape-config", dependencies=[Depends(verify_token)])
async def get_scrape_config():
    """获取刮削重命名配置"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _SCRAPE_CONFIG_KEY)
        )
        cfg = result.scalars().first()
        if cfg and cfg.value:
            try:
                return {**_SCRAPE_DEFAULTS, **_json.loads(cfg.value)}
            except (ValueError, TypeError):
                pass
    return {**_SCRAPE_DEFAULTS}


@router.post("/scrape-config", dependencies=[Depends(verify_token)])
async def save_scrape_config(payload: ScrapeConfigPayload):
    """保存刮削重命名配置"""
    value = _json.dumps(payload.model_dump(), ensure_ascii=False)
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _SCRAPE_CONFIG_KEY)
        )
        cfg = result.scalars().first()
        if cfg:
            cfg.value = value
            cfg.updated_at = tm.now()
        else:
            cfg = SystemConfig(
                key=_SCRAPE_CONFIG_KEY,
                value=value,
                description="115 刮削重命名配置",
                updated_at=tm.now(),
            )
            db.add(cfg)
        await db.commit()
    return {"success": True}


# ──────────────────── /p115/play/redirect_url 播放入口 ────────────────────
# 对齐 p115strmhelper redirect_url 协议，挂在 /api/v1/p115/play/redirect_url
# 无需鉴权（播放器直接访问）
#
# 支持两种形式：
#   参数形式：GET /api/v1/p115/play/redirect_url?pickcode={pickcode}
#   路径形式：GET /api/v1/p115/play/redirect_url/{pickcode}/{filename}
#
# 内部复用 RedirectService.resolve_any（与 /redirect_url 路由共享逻辑）

from fastapi import Request as _Request
from fastapi.responses import RedirectResponse as _RedirectResponse, JSONResponse as _JSONResponse
from src.services.redirect_service import RedirectService as _RedirectService

_play_redirect_svc = _RedirectService()


def _extract_play_params(request: _Request, pickcode: str = "", args_path: str = "") -> dict:
    """提取请求参数，路径中的 pickcode 优先于 query_params"""
    q = request.query_params
    return dict(
        pickcode=pickcode or q.get("pickcode", "") or q.get("pick_code", ""),
        pick_code="",
        args_path=args_path,
        path=q.get("path", ""),
        url=q.get("url", ""),
        file_name=q.get("file_name", "") or q.get("filename", ""),
        share_code=q.get("share_code", ""),
        receive_code=q.get("receive_code", ""),
        item_id=q.get("item_id", ""),
        storage_id=int(q.get("storage_id", 0) or 0),
        api_key=q.get("api_key", "") or q.get("X-Emby-Token", ""),
    )


async def _handle_play(request: _Request, pickcode: str = "", args_path: str = ""):
    """统一处理：pickcode → 直链 → 302"""
    params = _extract_play_params(request, pickcode=pickcode, args_path=args_path)
    result = await _play_redirect_svc.resolve_any(**params)
    if result.get("url"):
        logger.info("[p115/play] 302 → source=%s pickcode=%s", result.get("source"), params.get("pickcode"))
        return _RedirectResponse(url=result["url"], status_code=302)
    logger.warning("[p115/play] 解析失败: %s pickcode=%s", result.get("error"), params.get("pickcode"))
    return _JSONResponse(
        status_code=200,
        content={"error": result.get("error", "resolve failed"), "source": result.get("source", "")},
    )


# ── 参数形式：?pickcode=xxx ──────────────────────────────────────────────
@router.get("/play/redirect_url", include_in_schema=True, summary="115播放302入口（参数形式）")
async def p115_play_redirect_get(request: _Request):
    """`GET /api/v1/p115/play/redirect_url?pickcode={pickcode}&file_name={filename}`"""
    return await _handle_play(request)


@router.head("/play/redirect_url", include_in_schema=True, summary="115播放302入口（HEAD）")
async def p115_play_redirect_head(request: _Request):
    """HEAD /api/v1/p115/play/redirect_url — 播放器探测"""
    return await _handle_play(request)


@router.post("/play/redirect_url", include_in_schema=True, summary="115播放302入口（POST）")
async def p115_play_redirect_post(request: _Request):
    """POST /api/v1/p115/play/redirect_url"""
    return await _handle_play(request)


# ── 路径形式：/{pickcode}/{filename} — 必须在 /{pickcode} 之前注册 ────────
@router.get("/play/redirect_url/{pickcode}/{filename:path}", include_in_schema=True,
            summary="115播放302入口（路径形式）")
async def p115_play_redirect_path_get(pickcode: str, filename: str, request: _Request):
    """`GET /api/v1/p115/play/redirect_url/{pickcode}/{filename}`"""
    return await _handle_play(request, pickcode=pickcode, args_path=filename)


@router.head("/play/redirect_url/{pickcode}/{filename:path}", include_in_schema=True,
             summary="115播放302入口（路径形式 HEAD）")
async def p115_play_redirect_path_head(pickcode: str, filename: str, request: _Request):
    """HEAD /api/v1/p115/play/redirect_url/{pickcode}/{filename}"""
    return await _handle_play(request, pickcode=pickcode, args_path=filename)


# ── 路径形式：/{pickcode} 仅 pickcode，无文件名 ──────────────────────────
@router.get("/play/redirect_url/{pickcode}", include_in_schema=True,
            summary="115播放302入口（仅pickcode路径）")
async def p115_play_redirect_pickcode_get(pickcode: str, request: _Request):
    """`GET /api/v1/p115/play/redirect_url/{pickcode}`"""
    return await _handle_play(request, pickcode=pickcode)


@router.head("/play/redirect_url/{pickcode}", include_in_schema=True,
             summary="115播放302入口（仅pickcode路径 HEAD）")
async def p115_play_redirect_pickcode_head(pickcode: str, request: _Request):
    """HEAD /api/v1/p115/play/redirect_url/{pickcode}"""
    return await _handle_play(request, pickcode=pickcode)
