# src/services/ai_service.py
# AI 服务层 — 支持 OpenAI / Claude / 本地模型
#
# 功能:
#   - 对话助手（自然语言操作系统功能）
#   - 推断翻译（演员名/剧情翻译）
#   - 配置管理（存储到 SystemConfig）

import json
import logging
from typing import Optional, AsyncIterator

import httpx

from src.db import get_async_session_local
from src.db.models.system import SystemConfig
from sqlalchemy import select

logger = logging.getLogger(__name__)

# AI 配置键
AI_CONFIG_KEY = "ai_config"

# 内存缓存
_ai_config_cache: Optional[dict] = None


async def get_ai_config() -> dict:
    """从 SystemConfig 读取 AI 配置"""
    global _ai_config_cache
    if _ai_config_cache is not None:
        return _ai_config_cache

    async with get_async_session_local() as db:
        row = (await db.execute(
            select(SystemConfig).where(SystemConfig.key == AI_CONFIG_KEY)
        )).scalars().first()
        if row:
            _ai_config_cache = json.loads(row.value or "{}")
        else:
            _ai_config_cache = {}
    return _ai_config_cache


async def save_ai_config(config: dict) -> dict:
    """保存 AI 配置到 SystemConfig"""
    global _ai_config_cache
    async with get_async_session_local() as db:
        row = (await db.execute(
            select(SystemConfig).where(SystemConfig.key == AI_CONFIG_KEY)
        )).scalars().first()
        val = json.dumps(config, ensure_ascii=False)
        if row:
            row.value = val
        else:
            db.add(SystemConfig(key=AI_CONFIG_KEY, value=val))
        await db.commit()
    _ai_config_cache = config
    return {"success": True}


def invalidate_ai_cache():
    global _ai_config_cache
    _ai_config_cache = None


# ── 系统提示词 ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是 Misaka MediaFlow 的 AI 助手。你可以帮助用户:
1. 管理媒体库（查看统计、搜索媒体、查看会话等）
2. 管理 STRM 文件和同步任务
3. 管理 115 网盘
4. 演员信息翻译和清理
5. 系统配置和状态查看

请用中文回答，简洁准确。如果用户询问的功能你无法直接执行，请告知他们如何在 Web 界面操作。"""


class AIService:
    """AI 对话服务"""

    async def chat(self, messages: list[dict], stream: bool = False) -> dict:
        """发送对话请求"""
        config = await get_ai_config()
        provider = config.get("provider", "openai")
        api_key = config.get("api_key", "")
        base_url = config.get("base_url", "")
        model = config.get("model", "gpt-4o-mini")

        if not api_key:
            return {
                "success": False,
                "message": "AI 未配置，请先在设置中配置 API Key",
            }

        # 构建完整消息列表
        full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

        try:
            if provider in ("openai", "compatible"):
                return await self._call_openai(base_url, api_key, model, full_messages)
            elif provider == "claude":
                return await self._call_claude(base_url, api_key, model, full_messages)
            else:
                return await self._call_openai(base_url, api_key, model, full_messages)
        except Exception as e:
            logger.exception("AI 调用失败: %s", e)
            return {"success": False, "message": str(e)}

    async def _call_openai(self, base_url: str, api_key: str,
                           model: str, messages: list[dict]) -> dict:
        """OpenAI 兼容接口"""
        url = (base_url.rstrip("/") if base_url else "https://api.openai.com/v1")
        url = f"{url}/chat/completions"

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json={
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 2000,
            }, headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            })

        if resp.status_code != 200:
            return {"success": False, "message": f"API 错误: HTTP {resp.status_code}"}

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        return {
            "success": True,
            "content": content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }

    async def _call_claude(self, base_url: str, api_key: str,
                           model: str, messages: list[dict]) -> dict:
        """Claude API"""
        url = (base_url.rstrip("/") if base_url else "https://api.anthropic.com")
        url = f"{url}/v1/messages"

        # Claude 格式: system 单独传，messages 不含 system
        system_content = ""
        claude_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_content = m["content"]
            else:
                claude_msgs.append(m)

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json={
                "model": model or "claude-sonnet-4-20250514",
                "max_tokens": 2000,
                "system": system_content,
                "messages": claude_msgs,
            }, headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            })

        if resp.status_code != 200:
            return {"success": False, "message": f"API 错误: HTTP {resp.status_code}"}

        data = resp.json()
        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")
        usage = data.get("usage", {})
        return {
            "success": True,
            "content": content,
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        }

    async def translate_text(self, text: str, target_lang: str = "zh-CN") -> dict:
        """翻译文本"""
        messages = [{
            "role": "user",
            "content": f"请将以下文本翻译为{target_lang}，只返回翻译结果:\n\n{text}",
        }]
        return await self.chat(messages)


# ── 全局单例 ──────────────────────────────────────────────────────────
_ai_service: Optional[AIService] = None

def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service
