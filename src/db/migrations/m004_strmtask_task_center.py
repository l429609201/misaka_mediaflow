# src/db/migrations/m004_strmtask_task_center.py
"""
迁移 004: strmtask 表 — 补充任务中心所需字段

新增:
  task_name      TEXT        任务显示名称
  task_category  VARCHAR(64) 任务分类
  triggered_by   TEXT        触发来源
  extra_info     TEXT        额外信息 JSON

完全幂等：列已存在则跳过。
"""
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# 新增字段定义 (列名, DDL片段)
_NEW_COLUMNS = [
    ("task_name",     "TEXT NOT NULL DEFAULT ''"),
    ("task_category", "VARCHAR(64) NOT NULL DEFAULT 'p115_strm'"),
    ("triggered_by",  "TEXT NOT NULL DEFAULT 'manual'"),
    ("extra_info",    "TEXT NOT NULL DEFAULT ''"),
]


async def _column_exists(conn, db_type: str, table: str, column: str) -> bool:
    if db_type == "mysql":
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :tbl AND COLUMN_NAME = :col"
        ), {"tbl": table, "col": column})
    else:
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = :tbl AND column_name = :col"
        ), {"tbl": table, "col": column})
    return (result.scalar() or 0) > 0


async def upgrade(conn, db_type: str):
    for col_name, col_def in _NEW_COLUMNS:
        if await _column_exists(conn, db_type, "strmtask", col_name):
            continue
        logger.info("迁移 004: strmtask 补充字段 %s ...", col_name)
        try:
            await conn.execute(text(
                f"ALTER TABLE strmtask ADD COLUMN {col_name} {col_def}"
            ))
            logger.info("迁移 004: 字段 %s 添加完成", col_name)
        except Exception as e:
            logger.warning("迁移 004: 添加字段 %s 失败（可能已存在）: %s", col_name, e)

