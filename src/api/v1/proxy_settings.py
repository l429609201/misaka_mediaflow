# src/api/v1/proxy_settings.py
# HTTP 代理设置接口

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.core.security import verify_token
from src.services.proxy_config_service import load_from_db, save_to_db

router = APIRouter(prefix="/proxy-settings", tags=["proxy-settings"])


class ProxySettingsPayload(BaseModel):
    enabled: bool = False
    proxy_url: str = ""
    domains: list[str] = [
        "api.themoviedb.org",
        "image.tmdb.org",
    ]


@router.get("", dependencies=[Depends(verify_token)])
async def get_proxy_settings():
    """获取 HTTP 代理配置"""
    return await load_from_db()


@router.post("", dependencies=[Depends(verify_token)])
async def save_proxy_settings(payload: ProxySettingsPayload):
    """保存 HTTP 代理配置（同时刷新 core 层内存配置）"""
    await save_to_db(payload.model_dump())
    return {"success": True}


@router.post("/test", dependencies=[Depends(verify_token)])
async def test_proxy(payload: ProxySettingsPayload):
    """测试代理连通性（用当前填写的配置，不保存）"""
    import httpx
    proxy_url = payload.proxy_url.strip()
    if not payload.enabled or not proxy_url:
        return {"success": False, "message": "代理未启用或地址为空"}
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=8) as client:
            resp = await client.get("https://api.themoviedb.org/3/configuration?api_key=test")
            # 401 = API Key 错但网络通了，说明代理 OK
            reachable = resp.status_code in (200, 401)
        if reachable:
            return {"success": True, "message": "代理连接成功"}
        return {"success": False, "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

