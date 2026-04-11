# src/api/private/__init__.py
# Private API — 动态搜索源路由
#
# 路径: /api/private/{provider}/actions/{action_name}
# 路径: /api/private/{provider}/search
# 路径: /api/private/{provider}/details/{item_id}
#
# 每个 Provider 通过 SUPPORTED_ACTIONS + execute_action() 声明和实现自定义操作。
# 不需要为每个源写独立的路由文件。

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request, Body, Query
from src.core.security import verify_token
from src.services.metadata_service import metadata_service
from src.adapters.metadata.factory import MetadataFactory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/private", tags=["Private API"])


@router.post("/{provider}/actions/{action_name}", dependencies=[Depends(verify_token)])
async def execute_action(
    provider: str,
    action_name: str,
    payload: Optional[Dict[str, Any]] = Body(None),
    request: Request = None,
):
    """执行指定搜索源的自定义操作（如 BGM OAuth 授权流程）"""
    # 对于 action 类操作，Provider 可能还没 available（如还没授权），
    # 所以直接从工厂创建一个临时实例，不走 metadata_service.get_provider 的 available 检查
    provider_cls = MetadataFactory.get_provider_class(provider)
    if not provider_cls:
        return {"error": f"未知的搜索源: {provider}"}

    if action_name not in getattr(provider_cls, "SUPPORTED_ACTIONS", []):
        return {"error": f"搜索源 {provider} 不支持操作: {action_name}"}

    try:
        instance = MetadataFactory.create(provider)
        return await instance.execute_action(action_name, payload or {}, request=request)
    except Exception as e:
        logger.warning("[Private API] %s/%s 失败: %s", provider, action_name, e)
        return {"error": str(e)}


@router.get("/{provider}/search", dependencies=[Depends(verify_token)])
async def search_metadata(
    provider: str,
    keyword: str = Query(""),
    media_type: str = Query("tv"),
):
    """从指定搜索源搜索"""
    p = await metadata_service.get_provider(provider)
    if not p:
        return {"error": f"搜索源 {provider} 未配置或不可用", "results": []}
    try:
        results = await p.search(keyword, media_type=media_type)
        return {"results": [r.__dict__ for r in results]}
    except Exception as e:
        return {"error": str(e), "results": []}


@router.get("/{provider}/details/{item_id}", dependencies=[Depends(verify_token)])
async def get_details(
    provider: str,
    item_id: str,
    media_type: str = Query("tv"),
):
    """获取指定搜索源的详情"""
    p = await metadata_service.get_provider(provider)
    if not p:
        return {"error": f"搜索源 {provider} 未配置或不可用"}
    try:
        result = await p.get_detail(item_id, media_type=media_type)
        return result.__dict__ if result else {"error": "未找到详情"}
    except Exception as e:
        return {"error": str(e)}
