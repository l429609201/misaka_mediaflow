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
    扫描本地已注册的 MetadataProvider，结合数据库中保存的启用状态和字段覆盖值，
    返回可用搜索源列表（含每个 provider 的字段规格 fields）。
    """
    providers = MetadataFactory.list_providers()

    async with get_async_session_local() as db:
        enabled_map = await _load_json(db, _ENABLED_KEY)
        override_map = await _load_json(db, _OVERRIDE_KEY)

    result = []
    for p in providers:
        name = p["name"]
        saved = override_map.get(name, {})
        # 把 fields 默认值和已保存值合并，返回给前端当作表单初始值
        field_values = {}
        for f in p["fields"]:
            val = saved.get(f["key"], f.get("default", ""))
            # switch 类型转 boolean
            if f.get("type") == "switch":
                if isinstance(val, str):
                    val = val.lower() in ("true", "1", "yes")
            field_values[f["key"]] = val
        result.append({
            "key": name,
            "name": p["label"],
            "enabled": enabled_map.get(name, True),
            "status": "ok",
            "fields": p["fields"],         # 字段规格（前端据此动态渲染）
            "values": field_values,        # 当前已保存的字段值
        })
    return {"sources": result}


class SourceOverride(BaseModel):
    base_url: str = ""
    api_key: str = ""


class SavePayload(BaseModel):
    name: str
    enabled: bool = True
    values: dict = {}          # 通用字段值，key 对应 MetaFieldSpec.key


@router.post("/save", dependencies=[Depends(verify_token)])
async def save_source(payload: SavePayload):
    """保存单个搜索源的启用状态和字段值，同时刷新 metadata_service 缓存"""
    async with get_async_session_local() as db:
        enabled_map = await _load_json(db, _ENABLED_KEY)
        override_map = await _load_json(db, _OVERRIDE_KEY)

        enabled_map[payload.name] = payload.enabled
        override_map[payload.name] = payload.values

        await _save_json(db, _ENABLED_KEY, enabled_map)
        await _save_json(db, _OVERRIDE_KEY, override_map)

    # 配置更新后刷新该 Provider 的实例缓存，确保新配置立即生效
    from src.services.metadata_service import metadata_service
    metadata_service.invalidate_cache(payload.name)

    return {"success": True}


@router.post("/test/{name}", dependencies=[Depends(verify_token)])
async def test_source(name: str):
    """测试搜索源连接 — 绕过 available 检查，直接创建实例测试"""
    from src.adapters.metadata.factory import MetadataFactory
    import inspect as _inspect

    provider_cls = MetadataFactory.get_provider_class(name)
    if not provider_cls:
        return {"success": False, "message": f"未知的搜索源: {name}"}

    # 从 DB 读配置（和 _build_provider 一样的逻辑，但不做 available 检查）
    try:
        async with get_async_session_local() as db:
            cfg_data = {}
            config_key = provider_cls.CONFIG_KEY
            if config_key:
                row = await db.execute(select(SystemConfig).where(SystemConfig.key == config_key))
                cfg_row = row.scalars().first()
                if cfg_row and cfg_row.value:
                    cfg_data = json.loads(cfg_row.value)

            override_map = await _load_json(db, _OVERRIDE_KEY)
            source_vals = override_map.get(name, {})
            cfg_data = {**source_vals, **cfg_data}

        valid_keys = set(_inspect.signature(provider_cls.__init__).parameters) - {"self"}
        filtered = {k: v for k, v in cfg_data.items() if k in valid_keys}
        provider = MetadataFactory.create(name, **filtered)
        ok = await provider.test_connection()
        return {"success": ok, "message": "连接成功" if ok else "连接失败，请检查配置"}
    except Exception as e:
        return {"success": False, "message": str(e)}

