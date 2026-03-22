# src/db/migrations/m002_storageconfig_config_json.py
"""
迁移 002: storageconfig 表 — 散字段合并为 config JSON

将 username/password/token/extra 四列合并为单一 config TEXT 列。
完全幂等：config 列已存在则跳过。
"""
import json
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def upgrade(conn, db_type: str):
    # 1. 检查 config 列是否已存在
    if db_type == "mysql":
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'storageconfig' AND COLUMN_NAME = 'config'"
        ))
    else:
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = 'storageconfig' AND column_name = 'config'"
        ))

    if result.scalar() > 0:
        return  # 已迁移过

    logger.info("迁移 002: storageconfig → config JSON ...")

    # 2. 新增 config 列（MySQL TEXT 不支持 DEFAULT，先加列再填值）
    if db_type == "mysql":
        await conn.execute(text(
            "ALTER TABLE storageconfig ADD COLUMN config TEXT NOT NULL"
        ))
        # 给已有行填默认值
        await conn.execute(text(
            "UPDATE storageconfig SET config = '{}' WHERE config = ''"
        ))
    else:
        await conn.execute(text(
            "ALTER TABLE storageconfig ADD COLUMN config TEXT NOT NULL DEFAULT '{}'"
        ))

    # 3. 数据迁移：旧字段 → JSON
    rows = await conn.execute(text(
        "SELECT id, username, password, token, extra FROM storageconfig"
    ))
    for row in rows.fetchall():
        row_id, username, password, token, extra = row
        try:
            cfg = json.loads(extra or '{}')
        except Exception:
            cfg = {}
        if username:
            cfg['username'] = username
        if password:
            cfg['password'] = password
        if token:
            cfg['token'] = token
        await conn.execute(
            text("UPDATE storageconfig SET config = :cfg WHERE id = :id"),
            {"cfg": json.dumps(cfg, ensure_ascii=False), "id": row_id},
        )

    # 4. 删除旧列
    for col in ('username', 'password', 'token', 'extra'):
        try:
            await conn.execute(text(f"ALTER TABLE storageconfig DROP COLUMN {col}"))
        except Exception as e:
            logger.warning(f"迁移 002: 删除旧列 {col} 失败: {e}")

    logger.info("迁移 002: 完成")

