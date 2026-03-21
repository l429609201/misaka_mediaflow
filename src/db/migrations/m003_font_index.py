# src/db/migrations/m003_font_index.py
"""
迁移 003: 字体索引表 — font_file / font_face / font_name / subtitle_file

完全幂等：表已存在则跳过。
对应 src/db/models/font.py 的四张表。

级联关系（数据库层）：
  font_file  ←(1:N)─ font_face  ←(1:N)─ font_name
  subtitle_file 独立（软关联 mediaitem.item_id，无外键约束）

注意：外键 CASCADE 由数据库引擎保证，MySQL/PostgreSQL 均支持。
"""
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# 需要检查的四张表
_TABLES = ["font_file", "font_face", "font_name", "subtitle_file"]


async def _table_exists(conn, db_type: str, table_name: str) -> bool:
    """检查表是否已存在"""
    if db_type == "mysql":
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
        ), {"t": table_name})
    else:
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = :t"
        ), {"t": table_name})
    return (result.scalar() or 0) > 0


async def upgrade(conn, db_type: str):
    # 检查是否全部已建好，全部存在则跳过
    all_exist = all(
        [await _table_exists(conn, db_type, t) for t in _TABLES]
    )
    if all_exist:
        logger.debug("迁移 003: 字体索引表已存在，跳过")
        return

    logger.info("迁移 003: 创建字体索引表 ...")

    if db_type == "mysql":
        await _create_mysql(conn)
    else:
        await _create_postgresql(conn)

    logger.info("迁移 003: 完成")


async def _create_mysql(conn):
    # font_file
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS font_file (
            id          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            path        TEXT   NOT NULL                COMMENT '字体文件绝对路径',
            path_hash   VARCHAR(64) NOT NULL UNIQUE    COMMENT '路径MD5(唯一键)',
            file_size   BIGINT NOT NULL DEFAULT 0      COMMENT '文件大小(字节)',
            file_hash   VARCHAR(64) NOT NULL DEFAULT '' COMMENT '文件内容MD5',
            scanned_at  TEXT   NOT NULL DEFAULT ''     COMMENT '最近扫描时间',
            INDEX idx_font_file_file_hash (file_hash)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='字体文件索引'
    """))

    # font_face
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS font_face (
            id               BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            file_id          BIGINT NOT NULL                COMMENT '关联字体文件ID',
            face_index       INT    NOT NULL DEFAULT 0      COMMENT 'face序号',
            family_names     TEXT   NOT NULL DEFAULT '[]'   COMMENT 'Family名列表JSON',
            full_names       TEXT   NOT NULL DEFAULT '[]'   COMMENT 'Full名列表JSON',
            postscript_names TEXT   NOT NULL DEFAULT '[]'   COMMENT 'PostScript名列表JSON',
            weight           INT    NOT NULL DEFAULT 400    COMMENT '字重',
            is_bold          INT    NOT NULL DEFAULT 0      COMMENT '是否粗体',
            is_italic        INT    NOT NULL DEFAULT 0      COMMENT '是否斜体',
            scanned_at       TEXT   NOT NULL DEFAULT ''     COMMENT '扫描时间',
            INDEX idx_font_face_file_id (file_id),
            CONSTRAINT fk_font_face_file
                FOREIGN KEY (file_id) REFERENCES font_file(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='字体Face元数据'
    """))

    # font_name
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS font_name (
            id      BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            name    VARCHAR(512) NOT NULL               COMMENT '字体名(小写)',
            face_id BIGINT NOT NULL                     COMMENT '关联FontFace ID',
            INDEX idx_font_name_name (name),
            INDEX idx_font_name_face_id (face_id),
            CONSTRAINT fk_font_name_face
                FOREIGN KEY (face_id) REFERENCES font_face(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='字体名称索引'
    """))

    # subtitle_file
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS subtitle_file (
            id          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            item_id     VARCHAR(255) NOT NULL DEFAULT '' COMMENT '关联Emby媒体ID(软关联)',
            file_path   TEXT   NOT NULL                 COMMENT '字幕文件绝对路径',
            path_hash   VARCHAR(64) NOT NULL UNIQUE     COMMENT '路径MD5(唯一键)',
            file_hash   VARCHAR(64) NOT NULL DEFAULT '' COMMENT '文件内容MD5',
            file_size   BIGINT NOT NULL DEFAULT 0       COMMENT '文件大小(字节)',
            font_keys   TEXT   NOT NULL DEFAULT '[]'    COMMENT '字体key列表JSON',
            scanned_at  TEXT   NOT NULL DEFAULT ''      COMMENT '最近扫描时间',
            INDEX idx_subtitle_item_id (item_id),
            INDEX idx_subtitle_path_hash (path_hash)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='外部字幕文件登记'
    """))


async def _create_postgresql(conn):
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS font_file (
            id          BIGSERIAL PRIMARY KEY,
            path        TEXT        NOT NULL,
            path_hash   VARCHAR(64) NOT NULL UNIQUE,
            file_size   BIGINT      NOT NULL DEFAULT 0,
            file_hash   VARCHAR(64) NOT NULL DEFAULT '',
            scanned_at  TEXT        NOT NULL DEFAULT ''
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_font_file_file_hash ON font_file(file_hash)"
    ))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS font_face (
            id               BIGSERIAL PRIMARY KEY,
            file_id          BIGINT NOT NULL REFERENCES font_file(id) ON DELETE CASCADE,
            face_index       INTEGER NOT NULL DEFAULT 0,
            family_names     TEXT    NOT NULL DEFAULT '[]',
            full_names       TEXT    NOT NULL DEFAULT '[]',
            postscript_names TEXT    NOT NULL DEFAULT '[]',
            weight           INTEGER NOT NULL DEFAULT 400,
            is_bold          INTEGER NOT NULL DEFAULT 0,
            is_italic        INTEGER NOT NULL DEFAULT 0,
            scanned_at       TEXT    NOT NULL DEFAULT ''
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_font_face_file_id ON font_face(file_id)"
    ))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS font_name (
            id      BIGSERIAL PRIMARY KEY,
            name    VARCHAR(512) NOT NULL,
            face_id BIGINT NOT NULL REFERENCES font_face(id) ON DELETE CASCADE
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_font_name_name ON font_name(name)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_font_name_face_id ON font_name(face_id)"
    ))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS subtitle_file (
            id          BIGSERIAL PRIMARY KEY,
            item_id     VARCHAR(255) NOT NULL DEFAULT '',
            file_path   TEXT         NOT NULL,
            path_hash   VARCHAR(64)  NOT NULL UNIQUE,
            file_hash   VARCHAR(64)  NOT NULL DEFAULT '',
            file_size   BIGINT       NOT NULL DEFAULT 0,
            font_keys   TEXT         NOT NULL DEFAULT '[]',
            scanned_at  TEXT         NOT NULL DEFAULT ''
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_subtitle_item_id ON subtitle_file(item_id)"
    ))

