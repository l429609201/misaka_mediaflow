# src/services/ai_service.py
# AI 服务层 — 支持 OpenAI / Claude / 兼容模型
#
# 功能:
#   - 演员名翻译（带内存缓存 + 持久化统计）
#   - 剧情概述翻译
#   - 配置管理（存储到 SystemConfig）
#   - Token 用量统计
#   - 翻译缓存管理

import json
import logging
from typing import Optional

import httpx

from src.db import get_async_session_local
from src.db.models.system import SystemConfig
from sqlalchemy import select

logger = logging.getLogger(__name__)

# ── 配置 key ──────────────────────────────────────────────────────────
AI_CONFIG_KEY = "ai_config"
AI_STATS_KEY = "ai_stats"

# ── 内存缓存 ──────────────────────────────────────────────────────────
_ai_config_cache: Optional[dict] = None
_translate_cache: dict[str, str] = {}   # { "原名" -> "翻译名" }
_stats_cache: Optional[dict] = None     # token 统计


async def get_ai_config() -> dict:
    global _ai_config_cache
    if _ai_config_cache is not None:
        return _ai_config_cache
    async with get_async_session_local() as db:
        row = (await db.execute(
            select(SystemConfig).where(SystemConfig.key == AI_CONFIG_KEY)
        )).scalars().first()
        _ai_config_cache = json.loads(row.value or "{}") if row else {}
    return _ai_config_cache


async def save_ai_config(config: dict) -> dict:
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


# ── Token 统计持久化 ──────────────────────────────────────────────────

async def get_ai_stats() -> dict:
    global _stats_cache
    if _stats_cache is not None:
        return _stats_cache
    async with get_async_session_local() as db:
        row = (await db.execute(
            select(SystemConfig).where(SystemConfig.key == AI_STATS_KEY)
        )).scalars().first()
        _stats_cache = json.loads(row.value or "{}") if row else {}
    # 确保字段完整
    _stats_cache.setdefault("total_requests", 0)
    _stats_cache.setdefault("total_prompt_tokens", 0)
    _stats_cache.setdefault("total_completion_tokens", 0)
    _stats_cache.setdefault("total_tokens", 0)
    _stats_cache.setdefault("translate_requests", 0)
    _stats_cache.setdefault("cache_hits", 0)
    return _stats_cache


async def _save_stats():
    global _stats_cache
    if _stats_cache is None:
        return
    async with get_async_session_local() as db:
        row = (await db.execute(
            select(SystemConfig).where(SystemConfig.key == AI_STATS_KEY)
        )).scalars().first()
        val = json.dumps(_stats_cache, ensure_ascii=False)
        if row:
            row.value = val
        else:
            db.add(SystemConfig(key=AI_STATS_KEY, value=val))
        await db.commit()


async def _record_usage(usage: dict, is_translate: bool = False):
    stats = await get_ai_stats()
    stats["total_requests"] += 1
    stats["total_prompt_tokens"] += usage.get("prompt_tokens", 0)
    stats["total_completion_tokens"] += usage.get("completion_tokens", 0)
    stats["total_tokens"] += usage.get("total_tokens", 0)
    if is_translate:
        stats["translate_requests"] += 1
    await _save_stats()


async def reset_ai_stats() -> dict:
    global _stats_cache
    _stats_cache = {
        "total_requests": 0, "total_prompt_tokens": 0,
        "total_completion_tokens": 0, "total_tokens": 0,
        "translate_requests": 0, "cache_hits": 0,
    }
    await _save_stats()
    return {"success": True}


# ── 翻译缓存 ──────────────────────────────────────────────────────────

def get_translate_cache_stats() -> dict:
    return {"size": len(_translate_cache), "entries": dict(list(_translate_cache.items())[:50])}

def clear_translate_cache() -> dict:
    _translate_cache.clear()
    return {"success": True, "cleared": True}


class AIService:
    """AI 翻译服务"""

    async def translate_text(self, text: str, target_lang: str = "zh-CN") -> dict:
        """翻译文本（带缓存）"""
        cache_key = f"{text}|{target_lang}"
        if cache_key in _translate_cache:
            stats = await get_ai_stats()
            stats["cache_hits"] += 1
            await _save_stats()
            return {"success": True, "content": _translate_cache[cache_key], "cached": True}

        messages = [{
            "role": "user",
            "content": f"请将以下文本翻译为{target_lang}，只返回翻译结果:\n\n{text}",
        }]
        result = await self._call_llm(messages)
        if result.get("success") and result.get("content"):
            _translate_cache[cache_key] = result["content"]
            await _record_usage(result.get("usage", {}), is_translate=True)
        return result

    async def translate_actor_names(self, names: list[str]) -> dict:
        """批量翻译演员名"""
        if not names:
            return {"success": True, "results": {}, "cached": 0, "translated": 0}

        results = {}
        cached_count = 0
        translated_count = 0

        uncached = []
        for name in names:
            key = f"{name}|zh-CN"
            if key in _translate_cache:
                results[name] = _translate_cache[key]
                cached_count += 1
            else:
                uncached.append(name)

        if uncached:
            batch_text = "\n".join(f"- {n}" for n in uncached)
            messages = [{
                "role": "user",
                "content": (
                    "请将以下演员英文名翻译为中文名，每行一个，格式为「英文名 -> 中文名」，"
                    "如果无法确定中文名则保留原名：\n\n" + batch_text
                ),
            }]
            result = await self._call_llm(messages)
            if result.get("success") and result.get("content"):
                await _record_usage(result.get("usage", {}), is_translate=True)
                for line in result["content"].strip().split("\n"):
                    if "->" in line:
                        parts = line.split("->", 1)
                        en = parts[0].strip().lstrip("- ").strip()
                        cn = parts[1].strip()
                        if en and cn:
                            _translate_cache[f"{en}|zh-CN"] = cn
                            results[en] = cn
                            translated_count += 1

        if cached_count > 0:
            stats = await get_ai_stats()
            stats["cache_hits"] += cached_count
            await _save_stats()

        return {
            "success": True, "results": results,
            "cached": cached_count, "translated": translated_count,
        }

    async def _call_llm(self, messages: list[dict]) -> dict:
        """统一 LLM 调用入口"""
        config = await get_ai_config()
        provider = config.get("provider", "openai")
        api_key = config.get("api_key", "")
        base_url = config.get("base_url", "")
        model = config.get("model", "gpt-4o-mini")

        if not api_key:
            return {"success": False, "message": "AI 未配置 API Key"}

        try:
            if provider == "claude":
                return await self._call_claude(base_url, api_key, model, messages)
            else:
                return await self._call_openai(base_url, api_key, model, messages)
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
