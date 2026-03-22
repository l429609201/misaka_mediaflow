# src/db/database.py — 对齐 misaka_danmu_server 的 database.py
import logging
from typing import AsyncGenerator
from fastapi import FastAPI, Request
from sqlalchemy.engine.url import URL
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine, text, Column, BigInteger, Identity, Text
from sqlalchemy.orm import sessionmaker
from src.core.config import settings
from .base import Base

logger = logging.getLogger(__name__)


class DatabaseStartupError(Exception):
    """数据库启动失败异常，用于在 lifespan 中捕获并干净退出"""
    pass


# ==================== URL 构建 ====================

def _build_db_url(database: str = None) -> URL:
    """
    使用 SQLAlchemy URL.create() 构建连接 URL（自动处理密码转义）
    对齐弹幕库的 _build_db_url 模式
    """
    db_cfg = settings.database
    db_name = database or db_cfg.name

    if db_cfg.type == "mysql":
        return URL.create(
            drivername="mysql+aiomysql",
            username=db_cfg.user,
            password=db_cfg.password,
            host=db_cfg.host,
            port=db_cfg.port,
            database=db_name,
            query={"charset": "utf8mb4"},
        )
    else:  # postgresql
        return URL.create(
            drivername="postgresql+asyncpg",
            username=db_cfg.user,
            password=db_cfg.password,
            host=db_cfg.host,
            port=db_cfg.port,
            database=db_name,
        )


def _get_dsn_display() -> str:
    """用于日志输出的 DSN（隐藏密码）"""
    db_cfg = settings.database
    pwd = "***" if db_cfg.password else "(empty)"
    return f"{db_cfg.type}://{db_cfg.user}:{pwd}@{db_cfg.host}:{db_cfg.port}/{db_cfg.name}"


# ==================== 自动建库 ====================

async def _create_db_if_not_exists():
    """
    检查目标数据库是否存在，不存在则自动创建。
    对齐弹幕库的 _create_db_if_not_exists 模式。
    """
    db_cfg = settings.database
    db_name = db_cfg.name

    if db_cfg.type == "mysql":
        # MySQL: 连接到 information_schema（所有用户都有权限）
        admin_url = _build_db_url(database="information_schema")
    else:
        # PostgreSQL: 连接到 postgres 默认库
        admin_url = _build_db_url(database="postgres")

    try:
        engine = create_async_engine(
            admin_url,
            poolclass=AsyncAdaptedQueuePool,
            isolation_level="AUTOCOMMIT",   # CREATE DATABASE 必须在 autocommit 下执行
        )
        async with engine.connect() as conn:
            if db_cfg.type == "mysql":
                result = await conn.execute(
                    text("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = :name"),
                    {"name": db_name}
                )
                if not result.fetchone():
                    await conn.execute(text(
                        f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    ))
                    logger.info(f"Database '{db_name}' created (MySQL)")
            else:
                # PostgreSQL: 用 SQLAlchemy text() 查 pg_database，autocommit 引擎直接 CREATE DATABASE
                result = await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": db_name}
                )
                if not result.fetchone():
                    await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                    logger.info(f"Database '{db_name}' created (PostgreSQL)")
        await engine.dispose()
    except Exception as e:
        # 创建失败不一定致命（可能库已存在，或权限不够但库已建好）
        logger.warning(f"Auto-create database check failed (may be OK): {e}")


def _log_connection_error(error: Exception):
    """格式化输出数据库连接错误"""
    dsn = _get_dsn_display()
    root_cause = error.__cause__ if error.__cause__ else error
    error_str = str(root_cause)

    logger.error("")
    logger.error("=" * 60)
    logger.error("  数据库连接失败")
    logger.error("")
    logger.error(f"  地址  : {dsn}")
    logger.error(f"  错误  : {root_cause}")
    logger.error("")

    if "authentication failed" in error_str or "password" in error_str or "Access denied" in error_str:
        logger.error("  原因  : 用户名或密码错误")
        logger.error("  解决  : 检查 环境变量 ")
    elif "Connection refused" in error_str or "could not connect" in error_str:
        logger.error("  原因  : 数据库服务未启动或无法访问")
        logger.error("  解决  : 启动数据库服务，或检查 config.yaml 中的 host/port 配置")
    elif "does not exist" in error_str:
        logger.error("  原因  : 数据库或用户不存在")
        logger.error("  解决  : 创建对应的数据库和用户，或检查 config.yaml 配置")
    else:
        logger.error("  排查建议:")
        logger.error("    1. 数据库服务是否已启动？")
        logger.error("    2. config.yaml 中的 host/port/user/password 是否正确？")
        logger.error("    3. 数据库和用户是否已创建？")

    logger.error("=" * 60)
    logger.error("")


# ==================== 初始化（对齐弹幕库 init_db_tables） ====================

async def init_db_tables(app: FastAPI):
    """
    初始化数据库：自动建库 → 创建引擎 → 连通性检查 → create_all 建表 → 幂等迁移。
    存储 session_factory 到 app.state（对齐弹幕库模式）
    失败时抛出 DatabaseStartupError
    """
    db_cfg = settings.database
    dsn = _get_dsn_display()
    logger.info(f"连接数据库: {dsn}")

    # 1. 尝试自动建库
    await _create_db_if_not_exists()

    # 2. 创建主引擎
    db_url = _build_db_url()
    engine = create_async_engine(
        db_url,
        poolclass=AsyncAdaptedQueuePool,
        pool_size=db_cfg.pool_size,
        max_overflow=db_cfg.max_overflow,
        pool_recycle=3600,
        echo=False,
    )

    # 3. 检查连通性
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info(f"数据库连接成功: {dsn}")
    except Exception as e:
        _log_connection_error(e)
        await engine.dispose()
        raise DatabaseStartupError(f"Cannot connect to database: {e}")

    # 4. 自动建表（全新安装时创建，已有表自动跳过）
    import src.db.models  # noqa: F401 确保所有 model 被加载到 Base.metadata
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("数据库表结构检查/创建完成")
    except Exception as e:
        logger.error(f"创建数据库表失败: {e}")
        await engine.dispose()
        raise DatabaseStartupError(f"Cannot create tables: {e}")

    # 5. 幂等 schema 迁移（补字段、改字段，已存在就跳过）
    from src.db.migrations import run_all as run_migrations
    await run_migrations(engine)

    # 6. 创建 session factory → 存到 app.state
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    app.state.db_engine = engine
    app.state.session_factory = session_factory

    # 设置兼容层全局变量
    await _setup_compat(app)

    logger.info("数据库初始化完成")


async def close_db_engine(app: FastAPI):
    """关闭数据库引擎，释放连接池"""
    engine = getattr(app.state, "db_engine", None)
    if engine:
        await engine.dispose()
        logger.info("数据库引擎已关闭")


# ==================== 会话依赖注入（对齐弹幕库） ====================

async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话（用于 FastAPI Depends）
    对齐弹幕库的 get_db_session 模式：从 app.state 获取 session_factory
    """
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ==================== 兼容层（供 services / models 直接使用） ====================
# 全局引用，在 init_db_tables 后被赋值
AsyncSessionLocal = None
SyncSessionLocal = None


def get_async_session_local():
    """获取 AsyncSessionLocal（避免 import 时 None 的值拷贝问题）
    用法: async with get_async_session_local() as db:
    """
    if AsyncSessionLocal is None:
        raise RuntimeError("Database not initialized. AsyncSessionLocal is None.")
    return AsyncSessionLocal()


async def _setup_compat(app: FastAPI):
    """
    在 init_db_tables 成功后设置兼容层全局变量，并预加载 security 模块所需的初始数据。

    设计原则：
    - 不再创建同步引擎（消除 psycopg2/pg8000 等同步驱动依赖）
    - 所有 DB 操作均通过异步引擎完成，结果注入 security 模块全局变量
    - MySQL 的 SyncSessionLocal 仍通过 pymysql 提供（兼容老代码路径）
    """
    global AsyncSessionLocal, SyncSessionLocal
    AsyncSessionLocal = app.state.session_factory

    # MySQL 保留同步引擎（pymysql 已在 requirements.txt 中，无需额外驱动）
    db_cfg = settings.database
    if db_cfg.type == "mysql":
        sync_url = URL.create("mysql+pymysql", db_cfg.user, db_cfg.password,
                              db_cfg.host, db_cfg.port, db_cfg.name, {"charset": "utf8mb4"})
        sync_engine = create_engine(sync_url, pool_size=5, max_overflow=10, pool_recycle=3600)
        SyncSessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False,
                                        expire_on_commit=False)
        app.state.sync_engine = sync_engine
    # PostgreSQL 不创建同步引擎，所有操作通过异步接口完成

    # 异步预加载 security 模块所需初始数据（替代原来的同步 DB 查询）
    from src.core import security as _sec
    await _sec.async_preload_from_db(AsyncSessionLocal)


def get_id_column():
    """主键列 — BIGINT（供 ORM model 使用）"""
    if settings.database.type == "postgresql":
        return Column(BigInteger, Identity(start=1, cycle=True),
                      primary_key=True, index=True)
    else:
        return Column(BigInteger, primary_key=True,
                      autoincrement=True, index=True)


def get_time_column(comment: str = ""):
    """时间列 — TEXT 存储"""
    return Column(Text, default="", comment=comment)

