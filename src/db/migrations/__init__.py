# src/db/migrations/__init__.py
# 迁移管理器 — 自动发现并按序执行所有迁移任务
#
# 使用方式：
#   1. 在 src/db/migrations/ 下新建 mXXX_描述.py（如 m002_xxx.py）
#   2. 文件内实现 async def upgrade(conn, db_type: str) 函数
#   3. upgrade 必须幂等（列/表已存在就跳过）
#   4. 启动时自动按文件名排序依次执行

import logging
import importlib
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_all(engine):
    """
    扫描 migrations 目录下所有 mXXX_*.py 文件，
    按文件名排序依次调用其 upgrade(conn, db_type) 函数。
    每个迁移自行保证幂等。
    """
    from src.core.config import settings
    db_type = settings.database.type  # "mysql" / "postgresql"

    # 收集所有迁移模块（按文件名排序）
    migrations_dir = Path(__file__).parent
    migration_files = sorted(
        f.stem for f in migrations_dir.glob("m[0-9]*_*.py")
    )

    if not migration_files:
        logger.debug("无迁移任务")
        return

    logger.info(f"发现 {len(migration_files)} 个迁移任务: {migration_files}")

    async with engine.begin() as conn:
        for name in migration_files:
            module = importlib.import_module(f"src.db.migrations.{name}")
            upgrade_fn = getattr(module, "upgrade", None)
            if upgrade_fn is None:
                logger.warning(f"迁移 {name} 缺少 upgrade 函数，跳过")
                continue
            try:
                await upgrade_fn(conn, db_type)
            except Exception as e:
                logger.warning(f"迁移 {name} 执行失败（非致命）: {e}")

    logger.info("Schema 迁移检查完成")

