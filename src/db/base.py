# app/db/base.py
# ORM Base 基类 — 参考 MoviePilot，含 CRUD Mixin

from typing import Any

from sqlalchemy import select, inspect as sa_inspect
from sqlalchemy.orm import as_declarative, declared_attr, Session
from sqlalchemy.ext.asyncio import AsyncSession


@as_declarative()
class Base:
    """所有 ORM Model 的基类 — 含 CRUD Mixin"""
    id: Any
    __name__: str

    @declared_attr
    def __tablename__(self) -> str:
        """表名自动取类名小写"""
        return self.__name__.lower()

    # ==================== 同步 CRUD ====================

    def create(self, db: Session):
        """创建记录"""
        db.add(self)
        db.flush()
        return self

    @classmethod
    def get(cls, db: Session, rid: int):
        """按主键查询"""
        return db.query(cls).filter(cls.id == rid).first()

    def update_fields(self, db: Session, payload: dict):
        """更新指定字段"""
        for k, v in payload.items():
            if hasattr(self, k):
                setattr(self, k, v)
        if sa_inspect(self).detached:
            db.add(self)
        db.flush()
        return self

    @classmethod
    def delete_by_id(cls, db: Session, rid: int):
        """按主键删除"""
        db.query(cls).filter(cls.id == rid).delete()
        db.flush()

    @classmethod
    def truncate(cls, db: Session):
        """清空表"""
        db.query(cls).delete()
        db.flush()

    @classmethod
    def list_all(cls, db: Session):
        """查询全部"""
        return db.query(cls).all()

    # ==================== 异步 CRUD ====================

    async def async_create(self, db: AsyncSession):
        """异步创建"""
        db.add(self)
        await db.flush()
        return self

    @classmethod
    async def async_get(cls, db: AsyncSession, rid: int):
        """异步按主键查询"""
        result = await db.execute(select(cls).where(cls.id == rid))
        return result.scalars().first()

    async def async_update_fields(self, db: AsyncSession, payload: dict):
        """异步更新字段"""
        for k, v in payload.items():
            if hasattr(self, k):
                setattr(self, k, v)
        if sa_inspect(self).detached:
            db.add(self)
        await db.flush()
        return self

    @classmethod
    async def async_delete_by_id(cls, db: AsyncSession, rid: int):
        """异步按主键删除"""
        obj = await cls.async_get(db, rid)
        if obj:
            await db.delete(obj)
            await db.flush()

    @classmethod
    async def async_list_all(cls, db: AsyncSession):
        """异步查询全部"""
        result = await db.execute(select(cls))
        return result.scalars().all()

    # ==================== 序列化 ====================

    def to_dict(self) -> dict:
        """转为字典"""
        return {c.name: getattr(self, c.name, None) for c in self.__table__.columns}

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={getattr(self, 'id', '?')})>"

