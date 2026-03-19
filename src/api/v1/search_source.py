# src/api/v1/search_source.py
# 搜索源接口 — 基于本地已注册的 MetadataProvider 动态发现

import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from src.core.security import verify_token
from src.db import get_async_session_local
from src.db.models import SystemConfig
from src.adapters.metadata.factory import MetadataFactory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search-source", tags=["search-source"])

_ENABLED_KEY = "search_source_enabled"   # 存各 provider 的启用状态
_OVERRIDE_KEY = "search_source_override"  # 存各 provider 的 api_key / base_url 覆盖


async def _load_json(db, key: str) -> dict:
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    cfg = result.scalars().first()
    if cfg and cfg.value:
        try:
            return json.loads(cfg.value)
        except Exception:
            pass
    return {}


async def _save_json(db, key: str, data: dict) -> None:
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    cfg = result.scalars().first()
    value = json.dumps(data, ensure_ascii=False)
    if cfg:
        cfg.value = value
    else:
        db.add(SystemConfig(key=key, value=value, description=f"搜索源配置({key})"))
    await db.commit()


@router.get("/discover", dependencies=[Depends(verify_token)])
async def discover_sources():
    """
    扫描本地已注册的 MetadataProvider，结合数据库中保存的启用状态和覆盖配置，
    返回可用搜索源列表。
    """
    providers = MetadataFactory.list_providers()   # 只返回本地实际存在的

    async with get_async_session_local() as db:
        enabled_map = await _load_json(db, _ENABLED_KEY)
        override_map = await _load_json(db, _OVERRIDE_KEY)

    result = []
    for p in providers:
        name = p["name"]
        override = override_map.get(name, {})
        result.append({
            "key": name,
            "name": p["label"],
            "base_url": override.get("base_url", ""),
            "api_key": override.get("api_key", ""),
            # 默认启用，除非用户显式关闭
            "enabled": enabled_map.get(name, True),
            "status": "ok",
        })
    return {"sources": result}


class SourceOverride(BaseModel):
    base_url: str = ""
    api_key: str = ""


class SavePayload(BaseModel):
    # 保存单条 provider 的配置：启用状态 + 覆盖值
    name: str
    enabled: bool = True
    override: SourceOverride = SourceOverride()


@router.post("/save", dependencies=[Depends(verify_token)])
async def save_source(payload: SavePayload):
    """保存单个搜索源的启用状态和覆盖配置"""
    async with get_async_session_local() as db:
        enabled_map = await _load_json(db, _ENABLED_KEY)
        override_map = await _load_json(db, _OVERRIDE_KEY)

        enabled_map[payload.name] = payload.enabled
        override_map[payload.name] = {
            "base_url": payload.override.base_url,
            "api_key": payload.override.api_key,
        }

        await _save_json(db, _ENABLED_KEY, enabled_map)
        await _save_json(db, _OVERRIDE_KEY, override_map)

    return {"success": True}

