# src/api/v1/ai.py
# AI 对话助手 API

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from src.core.security import verify_token
from src.services.ai_service import (
    get_ai_service, get_ai_config, save_ai_config, invalidate_ai_cache,
)

router = APIRouter(prefix="/ai", tags=["AI 助手"])


# ── 配置 ──────────────────────────────────────────────────────────────

@router.get("/config", dependencies=[Depends(verify_token)])
async def get_config():
    """获取 AI 配置"""
    config = await get_ai_config()
    # 不返回完整 api_key，脱敏
    safe = {**config}
    if safe.get("api_key"):
        key = safe["api_key"]
        safe["api_key"] = key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
        safe["api_key_set"] = True
    else:
        safe["api_key_set"] = False
    return safe


class AIConfigPayload(BaseModel):
    provider: str = "openai"        # openai / claude / compatible
    api_key: str = ""
    base_url: str = ""
    model: str = "gpt-4o-mini"


@router.post("/config", dependencies=[Depends(verify_token)])
async def update_config(payload: AIConfigPayload):
    """保存 AI 配置"""
    data = payload.model_dump()
    # 如果 api_key 是脱敏的，保留旧值
    if "****" in data.get("api_key", ""):
        old = await get_ai_config()
        data["api_key"] = old.get("api_key", "")
    invalidate_ai_cache()
    return await save_ai_config(data)


# ── 对话 ──────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str = "user"
    content: str = ""


class ChatPayload(BaseModel):
    messages: list[ChatMessage]
    context: Optional[str] = None


@router.post("/chat", dependencies=[Depends(verify_token)])
async def chat(payload: ChatPayload):
    """AI 对话"""
    svc = get_ai_service()
    messages = [m.model_dump() for m in payload.messages]
    return await svc.chat(messages)


# ── 翻译 ──────────────────────────────────────────────────────────────

class TranslatePayload(BaseModel):
    text: str
    target_lang: str = "zh-CN"


@router.post("/translate", dependencies=[Depends(verify_token)])
async def translate(payload: TranslatePayload):
    """AI 翻译"""
    svc = get_ai_service()
    return await svc.translate_text(payload.text, payload.target_lang)
