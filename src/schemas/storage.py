# app/schemas/storage.py
# 存储相关 Pydantic 模型

import json
from pydantic import BaseModel, field_validator


class StorageConfigCreate(BaseModel):
    name: str
    type: str               # clouddrive2 / alist / p115
    host: str
    config: dict = {}       # 适配器自定义字段，整体存取


class StorageConfigOut(BaseModel):
    id: int
    name: str
    type: str
    host: str
    config: dict = {}       # secret 字段已脱敏（值替换为 True，表示"已设置"）
    is_active: int = 1
    created_at: str = ""
    updated_at: str = ""

    model_config = {"from_attributes": True}

    @field_validator("config", mode="before")
    @classmethod
    def _parse_config(cls, v):
        """ORM 返回的是 JSON 字符串，自动解析为 dict"""
        if isinstance(v, str):
            try:
                return json.loads(v) if v else {}
            except (json.JSONDecodeError, TypeError):
                return {}
        return v if isinstance(v, dict) else {}


class PathMappingCreate(BaseModel):
    storage_id: int
    local_prefix: str
    cloud_prefix: str
    priority: int = 0


class PathMappingOut(BaseModel):
    id: int
    storage_id: int
    local_prefix: str
    cloud_prefix: str
    priority: int = 0
    is_active: int = 1
    created_at: str = ""

    model_config = {"from_attributes": True}

