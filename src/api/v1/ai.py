# src/api/v1/ai.py
# AI 配置 + 余额 + 模型列表 + 翻译 + 统计 + 缓存 API

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.core.security import verify_token
from src.services.ai_service import (
    get_ai_service, get_ai_config, save_ai_config, invalidate_ai_cache,
    get_ai_stats, reset_ai_stats,
    get_translate_cache_stats, clear_translate_cache,
)

router = APIRouter(prefix="/ai", tags=["AI 服务"])


# ── 配置 ──────────────────────────────────────────────────────────────

@router.get("/config", dependencies=[Depends(verify_token)])
async def get_config():
    config = await get_ai_config()
    safe = {**config}
    # 不返回 api_key 值，只返回是否已设置
    safe["api_key_set"] = bool(safe.get("api_key"))
    safe.pop("api_key", None)
    return safe


class AIConfigPayload(BaseModel):
    provider: str = "openai"
    api_key: str = ""
    base_url: str = ""
    model: str = "gpt-4o-mini"
    actor_translate_enabled: bool = False
    overview_translate_enabled: bool = False


@router.post("/config", dependencies=[Depends(verify_token)])
async def update_config(payload: AIConfigPayload):
    data = payload.model_dump()
    # api_key 为空则保留旧值
    if not data.get("api_key"):
        old = await get_ai_config()
        data["api_key"] = old.get("api_key", "")
    invalidate_ai_cache()
    return await save_ai_config(data)


# ── 账户余额 ──────────────────────────────────────────────────────────

@router.get("/balance", dependencies=[Depends(verify_token)])
async def get_balance():
    config = await get_ai_config()
    provider = config.get("provider", "")
    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "")
    if not api_key:
        return {"supported": False}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if provider == "deepseek" or "deepseek" in (base_url or ""):
                url = (base_url.rstrip("/").replace("/v1", "") if base_url else "https://api.deepseek.com")
                resp = await client.get(f"{url}/user/balance", headers={"Authorization": f"Bearer {api_key}"})
                if resp.status_code == 200:
                    info = resp.json().get("balance_infos", [{}])
                    total = sum(float(b.get("total_balance", 0)) for b in info)
                    granted = sum(float(b.get("granted_balance", 0)) for b in info)
                    topped = sum(float(b.get("topped_up_balance", 0)) for b in info)
                    return {"supported": True, "provider": "DeepSeek", "currency": "CNY",
                            "total": round(total, 2), "granted": round(granted, 2), "topped_up": round(topped, 2)}
            if provider == "siliconflow" or "siliconflow" in (base_url or ""):
                url = (base_url.rstrip("/").replace("/v1", "") if base_url else "https://api.siliconflow.cn")
                resp = await client.get(f"{url}/v1/user/info", headers={"Authorization": f"Bearer {api_key}"})
                if resp.status_code == 200:
                    bal = float(resp.json().get("data", {}).get("balance", 0))
                    return {"supported": True, "provider": "硅基流动", "currency": "CNY",
                            "total": round(bal, 2), "granted": 0, "topped_up": round(bal, 2)}
    except Exception as e:
        return {"supported": False, "message": str(e)}
    return {"supported": False}


# ── 模型列表 ──────────────────────────────────────────────────────────

_DEFAULT_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "compatible": "",
}

@router.get("/models", dependencies=[Depends(verify_token)])
async def list_models():
    config = await get_ai_config()
    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "")
    provider = config.get("provider", "openai")
    if not api_key:
        return {"items": []}
    url = (base_url.rstrip("/") if base_url else _DEFAULT_URLS.get(provider, ""))
    if not url:
        return {"items": []}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{url}/models", headers={"Authorization": f"Bearer {api_key}"})
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                items = sorted([{"id": m.get("id", ""), "owned_by": m.get("owned_by", "")} for m in models], key=lambda x: x["id"])
                return {"items": items}
    except Exception:
        pass
    return {"items": []}


# ── 统计 / 缓存 / 翻译 / 测试 ────────────────────────────────────────

@router.get("/stats", dependencies=[Depends(verify_token)])
async def get_stats():
    return await get_ai_stats()

@router.post("/stats/reset", dependencies=[Depends(verify_token)])
async def reset_stats():
    return await reset_ai_stats()

@router.get("/cache", dependencies=[Depends(verify_token)])
async def get_cache():
    return get_translate_cache_stats()

@router.post("/cache/clear", dependencies=[Depends(verify_token)])
async def clear_cache():
    return clear_translate_cache()

class TranslatePayload(BaseModel):
    text: str
    target_lang: str = "zh-CN"

@router.post("/translate", dependencies=[Depends(verify_token)])
async def translate(payload: TranslatePayload):
    return await get_ai_service().translate_text(payload.text, payload.target_lang)

class BatchTranslatePayload(BaseModel):
    names: list[str]

@router.post("/translate/actors", dependencies=[Depends(verify_token)])
async def translate_actors(payload: BatchTranslatePayload):
    return await get_ai_service().translate_actor_names(payload.names)

@router.post("/test", dependencies=[Depends(verify_token)])
async def test_connection():
    return await get_ai_service().translate_text("hello", "zh-CN")
