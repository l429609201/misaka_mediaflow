# app/api/v1/storage.py
# 存储管理 API — 存储源 CRUD + 路径映射 CRUD
# config 字段统一用 JSON 存储，适配器自定义字段，secret 字段脱敏回传

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func

from src.core.security import verify_token
from src.core.timezone import tm
from src.db import get_async_session_local
from src.db.models import StorageConfig, PathMapping
from src.schemas.storage import (
    StorageConfigCreate, StorageConfigOut, PathMappingCreate, PathMappingOut,
)
from src.adapters.storage.factory import StorageFactory

router = APIRouter(prefix="/storage", tags=["存储管理"])


# ──────────────────── 内部辅助 ────────────────────

def _load_config(storage: StorageConfig) -> dict:
    """从数据库 config 字段解析 JSON，容错处理。"""
    try:
        return json.loads(storage.config or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _serialize_storage(storage: StorageConfig) -> dict:
    """
    序列化存储源：返回真实 config 值。
    管理后台场景，管理员需要查看自己设的密钥，
    前端用 Input.Password 自带遮罩 + 眼睛切换即可。
    """
    raw_config = _load_config(storage)
    fields = StorageFactory.get_fields(storage.type)
    safe_config: dict = {}
    for f in fields:
        safe_config[f.key] = raw_config.get(f.key, f.default)
    out = StorageConfigOut.model_validate(storage).model_dump()
    out["config"] = safe_config
    return out


def _build_config(storage_type: str, new_config: dict, old_config: dict | None = None) -> str:
    """
    合并新旧 config，只保留该适配器声明的字段。
    secret 字段：空字符串 → 保留旧值（未修改），非空 → 用新值覆盖。
    """
    fields = StorageFactory.get_fields(storage_type)
    old = old_config or {}
    result: dict = {}
    for f in fields:
        new_val = new_config.get(f.key, "")
        if f.secret and new_val == "":
            # 空字符串表示未修改，保留旧值
            result[f.key] = old.get(f.key, "")
        else:
            result[f.key] = new_val
    return json.dumps(result, ensure_ascii=False)


# ──────────────────── 元信息 ────────────────────

@router.get("/meta", dependencies=[Depends(verify_token)])
async def get_storage_meta():
    """返回所有存储类型的字段规格，前端据此动态渲染配置表单。"""
    return {"types": StorageFactory.get_meta()}


# ──────────────────── 存储源 CRUD ────────────────────

@router.get("", dependencies=[Depends(verify_token)])
async def list_storages(page: int = 1, size: int = 20):
    async with get_async_session_local() as db:
        total = (await db.execute(select(func.count()).select_from(StorageConfig))).scalar() or 0
        result = await db.execute(
            select(StorageConfig).order_by(StorageConfig.id.desc())
            .offset((page - 1) * size).limit(size)
        )
        return {
            "items": [_serialize_storage(i) for i in result.scalars().all()],
            "total": total, "page": page, "size": size,
        }


@router.post("", dependencies=[Depends(verify_token)])
async def create_storage(payload: StorageConfigCreate):
    async with get_async_session_local() as db:
        storage = StorageConfig(
            name=payload.name, type=payload.type, host=payload.host,
            config=_build_config(payload.type, payload.config),
            created_at=tm.now(), updated_at=tm.now(),
        )
        db.add(storage)
        await db.commit()
        await db.refresh(storage)
        return {"success": True, "id": storage.id}


@router.get("/{storage_id}", dependencies=[Depends(verify_token)])
async def get_storage(storage_id: int):
    async with get_async_session_local() as db:
        storage = (await db.execute(
            select(StorageConfig).where(StorageConfig.id == storage_id)
        )).scalars().first()
        if not storage:
            raise HTTPException(status_code=404, detail="storage not found")
        return _serialize_storage(storage)


@router.put("/{storage_id}", dependencies=[Depends(verify_token)])
async def update_storage(storage_id: int, payload: StorageConfigCreate):
    async with get_async_session_local() as db:
        storage = (await db.execute(
            select(StorageConfig).where(StorageConfig.id == storage_id)
        )).scalars().first()
        if not storage:
            raise HTTPException(status_code=404, detail="storage not found")
        old_config = _load_config(storage)
        storage.name = payload.name
        storage.type = payload.type
        storage.host = payload.host
        storage.config = _build_config(payload.type, payload.config, old_config)
        storage.updated_at = tm.now()
        await db.commit()
        return {"success": True}


@router.delete("/{storage_id}", dependencies=[Depends(verify_token)])
async def delete_storage(storage_id: int):
    async with get_async_session_local() as db:
        storage = (await db.execute(
            select(StorageConfig).where(StorageConfig.id == storage_id)
        )).scalars().first()
        if not storage:
            raise HTTPException(status_code=404, detail="storage not found")
        await db.delete(storage)
        await db.commit()
        return {"success": True}


@router.post("/{storage_id}/test", dependencies=[Depends(verify_token)])
async def test_storage(storage_id: int):
    async with get_async_session_local() as db:
        storage = (await db.execute(
            select(StorageConfig).where(StorageConfig.id == storage_id)
        )).scalars().first()
        if not storage:
            raise HTTPException(status_code=404, detail="storage not found")
        try:
            adapter = StorageFactory.create(
                storage.type, host=storage.host, config=_load_config(storage)
            )
            return {"success": await adapter.test_connection()}
        except Exception as e:
            return {"success": False, "error": str(e)}


@router.get("/{storage_id}/space", dependencies=[Depends(verify_token)])
async def get_storage_space(storage_id: int):
    """获取存储源容量信息"""
    async with get_async_session_local() as db:
        storage = (await db.execute(
            select(StorageConfig).where(StorageConfig.id == storage_id)
        )).scalars().first()
        if not storage:
            raise HTTPException(status_code=404, detail="storage not found")
        try:
            adapter = StorageFactory.create(
                storage.type, host=storage.host, config=_load_config(storage)
            )
            usage = await adapter.get_space_usage()
            return {"success": True, **usage}
        except Exception as e:
            return {"success": False, "total": 0, "used": 0, "free": 0, "error": str(e)}


@router.get("/{storage_id}/tree", dependencies=[Depends(verify_token)])
async def browse_storage_tree(storage_id: int, path: str = "/"):
    async with get_async_session_local() as db:
        storage = (await db.execute(
            select(StorageConfig).where(StorageConfig.id == storage_id)
        )).scalars().first()
        if not storage:
            raise HTTPException(status_code=404, detail="storage not found")
        try:
            adapter = StorageFactory.create(
                storage.type, host=storage.host, config=_load_config(storage)
            )
            entries = await adapter.list_files(path)
            items = []
            for e in entries:
                items.append({
                    "key": e.path,
                    "title": e.name,
                    "path": e.path,
                    "isLeaf": not e.is_dir,
                    "is_dir": e.is_dir,
                    "size": e.size,
                })
            # 目录排前面，文件排后面
            items.sort(key=lambda x: (not x["is_dir"], x["title"]))
            return {"items": items, "path": path}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


# ──────────────────── 路径映射 CRUD ────────────────────

@router.get("/mappings", dependencies=[Depends(verify_token)])
async def list_mappings(storage_id: int = 0, page: int = 1, size: int = 50):
    async with get_async_session_local() as db:
        q = select(PathMapping)
        cq = select(func.count()).select_from(PathMapping)
        if storage_id > 0:
            q = q.where(PathMapping.storage_id == storage_id)
            cq = cq.where(PathMapping.storage_id == storage_id)
        total = (await db.execute(cq)).scalar() or 0
        result = await db.execute(
            q.order_by(PathMapping.priority.desc()).offset((page - 1) * size).limit(size)
        )
        return {
            "items": [PathMappingOut.model_validate(i).model_dump() for i in result.scalars().all()],
            "total": total, "page": page, "size": size,
        }


@router.post("/mappings", dependencies=[Depends(verify_token)])
async def create_mapping(payload: PathMappingCreate):
    async with get_async_session_local() as db:
        mapping = PathMapping(
            storage_id=payload.storage_id, local_prefix=payload.local_prefix,
            cloud_prefix=payload.cloud_prefix, priority=payload.priority,
            created_at=tm.now(),
        )
        db.add(mapping)
        await db.commit()
        await db.refresh(mapping)
        return {"success": True, "id": mapping.id}


@router.delete("/mappings/{mapping_id}", dependencies=[Depends(verify_token)])
async def delete_mapping(mapping_id: int):
    async with get_async_session_local() as db:
        mapping = (await db.execute(
            select(PathMapping).where(PathMapping.id == mapping_id)
        )).scalars().first()
        if not mapping:
            raise HTTPException(status_code=404, detail="mapping not found")
        await db.delete(mapping)
        await db.commit()
        return {"success": True}

