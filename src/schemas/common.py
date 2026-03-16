# app/schemas/common.py
# 通用 Pydantic 模型

from typing import Any, Optional
from pydantic import BaseModel


class PageQuery(BaseModel):
    """分页查询参数"""
    page: int = 1
    size: int = 20
    keyword: Optional[str] = None


class PageResult(BaseModel):
    """分页结果"""
    items: list[Any] = []
    total: int = 0
    page: int = 1
    size: int = 20


class ResponseModel(BaseModel):
    """统一响应格式"""
    success: bool = True
    message: str = "ok"
    data: Any = None

