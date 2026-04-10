# src/api/v1/ai.py
# AI 配置 + 翻译 + 统计 + 缓存 API

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

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
    if safe.get("api_key"):
        key = safe["api_key"]
        safe["api_key"] = key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
        safe["api_key_set"] = True
    else:
        safe["api_key_set"] = False
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
    if "****" in data.get("api_key", ""):
        old = await get_ai_config()
        data["api_key"] = old.get("api_key", "")
    invalidate_ai_cache()
    return await save_ai_config(data)


# ── 统计 ──────────────────────────────────────────────────────────────

@router.get("/stats", dependencies=[Depends(verify_token)])
async def get_stats():
    return await get_ai_stats()


@router.post("/stats/reset", dependencies=[Depends(verify_token)])
async def reset_stats():
    return await reset_ai_stats()


# ── 翻译缓存 ──────────────────────────────────────────────────────────

@router.get("/cache", dependencies=[Depends(verify_token)])
async def get_cache():
    return get_translate_cache_stats()


@router.post("/cache/clear", dependencies=[Depends(verify_token)])
async def clear_cache():
    return clear_translate_cache()


# ── 翻译 ──────────────────────────────────────────────────────────────

class TranslatePayload(BaseModel):
    text: str
    target_lang: str = "zh-CN"


@router.post("/translate", dependencies=[Depends(verify_token)])
async def translate(payload: TranslatePayload):
    svc = get_ai_service()
    return await svc.translate_text(payload.text, payload.target_lang)


class BatchTranslatePayload(BaseModel):
    names: list[str]


@router.post("/translate/actors", dependencies=[Depends(verify_token)])
async def translate_actors(payload: BatchTranslatePayload):
    svc = get_ai_service()
    return await svc.translate_actor_names(payload.names)


# ── 连接测试 ──────────────────────────────────────────────────────────

@router.post("/test", dependencies=[Depends(verify_token)])
async def test_connection():
    svc = get_ai_service()
    result = await svc.translate_text("hello", "zh-CN")
    return result
