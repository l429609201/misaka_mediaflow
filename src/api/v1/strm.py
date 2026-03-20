# app/api/v1/strm.py
# STRM 管理 API

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from src.core.security import verify_token
from src.services.strm_service import StrmService
from src.db import get_async_session_local
from src.db.models import SystemConfig

router = APIRouter(prefix="/strm", tags=["STRM 管理"])
_strm_service = StrmService()

_URL_TEMPLATE_KEY = "strm_url_template"

# 115STRM 默认模板（Jinja2 语法）
_DEFAULT_TEMPLATE = (
    "{{ base_url }}?pickcode={{ pickcode }}"
    "{% if file_name %}&file_name={{ file_name | urlencode }}{% endif %}"
)


@router.get("/url-template", dependencies=[Depends(verify_token)])
async def get_url_template():
    """获取 STRM URL 模板"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _URL_TEMPLATE_KEY)
        )
        cfg = result.scalars().first()
        template = json.loads(cfg.value) if cfg and cfg.value else _DEFAULT_TEMPLATE
    return {"template": template}


class UrlTemplatePayload(BaseModel):
    template: str


@router.post("/url-template", dependencies=[Depends(verify_token)])
async def save_url_template(payload: UrlTemplatePayload):
    """保存 STRM URL 模板"""
    async with get_async_session_local() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == _URL_TEMPLATE_KEY)
        )
        cfg = result.scalars().first()
        value = json.dumps(payload.template, ensure_ascii=False)
        if cfg:
            cfg.value = value
        else:
            db.add(SystemConfig(
                key=_URL_TEMPLATE_KEY,
                value=value,
                description="STRM URL 拼接模板（Jinja2）",
            ))
        await db.commit()
    return {"success": True}


@router.get("/tasks", dependencies=[Depends(verify_token)])
async def list_tasks(page: int = 1, size: int = 20):
    """分页获取 STRM 任务列表"""
    return await _strm_service.list_tasks(page, size)


@router.post("/tasks", dependencies=[Depends(verify_token)])
async def create_task(task_type: str = "manual"):
    """手动触发 STRM 生成"""
    return await _strm_service.create_task(task_type)


@router.get("/tasks/{task_id}", dependencies=[Depends(verify_token)])
async def get_task_status(task_id: int):
    """获取单个任务状态"""
    return await _strm_service.get_task_status(task_id)


@router.get("/files", dependencies=[Depends(verify_token)])
async def list_strm_files(task_id: int = 0, page: int = 1, size: int = 20):
    """分页获取 STRM 文件列表"""
    return await _strm_service.list_files(task_id, page, size)

