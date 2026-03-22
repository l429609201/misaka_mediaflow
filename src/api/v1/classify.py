# src/api/v1/classify.py
# 通用整理分类引擎 API
# 前端「整理分类」模块唯一对接点；与 115 平台无关。

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional

from src.core.security import verify_token
import src.services.classify_engine as classify_engine
from src.services.metadata_service import metadata_service

router = APIRouter(prefix="/classify", tags=["整理分类引擎"])


# ─── 请求体模型 ───────────────────────────────────────────────────────────────

class RuleItem(BaseModel):
    type: str
    field: Optional[str] = "filename"
    value: str = ""


class CategoryItem(BaseModel):
    name: str
    target_dir: str = ""
    match_all: bool = False
    rules: List[RuleItem] = []


class ClassifyConfigPayload(BaseModel):
    enabled: bool = True
    dry_run: bool = False
    target_root: str = ""
    unrecognized_dir: str = ""
    categories: List[CategoryItem] = []


# ─── 分类配置读写 ─────────────────────────────────────────────────────────────

@router.get("/config", dependencies=[Depends(verify_token)])
async def get_classify_config():
    """获取分类引擎配置（含规则列表）"""
    return await classify_engine.get_config()


@router.post("/config", dependencies=[Depends(verify_token)])
async def save_classify_config(payload: ClassifyConfigPayload):
    """保存分类引擎配置，同时刷新 metadata_service 缓存"""
    await classify_engine.save_config(payload.model_dump())
    # 配置保存后刷新 metadata provider 缓存，确保新配置立即生效
    metadata_service.invalidate_cache()
    return {"success": True}


# ─── 元数据 Provider 状态查询（通用，不限于 TMDB）────────────────────────────

@router.get("/metadata-status", dependencies=[Depends(verify_token)])
async def get_metadata_status():
    """
    返回所有已注册元数据 Provider 的可用状态。
    [{"name": "tmdb", "label": "TMDB", "available": true}, ...]
    """
    return await metadata_service.list_available_providers()


@router.get("/tmdb-status", dependencies=[Depends(verify_token)])
async def get_tmdb_status():
    """兼容旧接口：仅返回 TMDB 可用状态"""
    available = await metadata_service.is_provider_available("tmdb")
    return {"available": available}

