# reset_password.py — 重置管理员密码
# 对齐 misaka_danmu_server 的 reset_password.py 模式
#
# 使用方式:
#   python reset_password.py              # 重置 admin 密码
#   python reset_password.py admin        # 指定用户名
#   python reset_password.py --help       # 查看帮助

import asyncio
import argparse
import secrets
import string
import os
import sys
from pathlib import Path

# 将项目根目录添加到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text

from src.core.config import settings
from src.core.security import hash_password, ADMIN_USERNAME
from src.db.database import _build_db_url


async def reset_password(username: str):
    """
    为指定用户重置密码（操作 user 表）。
    """
    # 1. 构建数据库连接
    try:
        db_url = _build_db_url()
    except Exception as e:
        print(f"[ERROR] database config error: {e}")
        return

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # user 是 MySQL 保留字，需要加引号
    qt = "`" if settings.database.type == "mysql" else '"'
    tbl = f"{qt}user{qt}"

    async with session_factory() as session:
        # 2. 检查 user 表是否存在以及用户是否存在
        try:
            result = await session.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE username = :username"),
                {"username": username}
            )
            row = result.scalar()
        except Exception as e:
            print(f"[ERROR] query failed (table may not exist, start the service first): {e}")
            await engine.dispose()
            return

        # 3. 生成新的 16 位随机密码
        alphabet = string.ascii_letters + string.digits
        new_password = ''.join(secrets.choice(alphabet) for _ in range(16))

        # 4. 哈希密码
        hashed_password = hash_password(new_password)

        # 5. 写入 user 表
        try:
            from src.core.timezone import tm
            now = tm.now()

            if row and row > 0:
                # 更新已有用户
                await session.execute(
                    text(f"UPDATE {tbl} SET password_hash = :hash, updated_at = :now WHERE username = :username"),
                    {"hash": hashed_password, "now": now, "username": username}
                )
            else:
                # 插入新用户
                await session.execute(
                    text(
                        f"INSERT INTO {tbl} (username, password_hash, role, is_active, created_at, updated_at) "
                        "VALUES (:username, :hash, :role, :active, :now, :now)"
                    ),
                    {
                        "username": username,
                        "hash": hashed_password,
                        "role": "admin",
                        "active": 1,
                        "now": now,
                    }
                )
            await session.commit()
        except Exception as e:
            print(f"[ERROR] failed to write password: {e}")
            await engine.dispose()
            return

        # 6. 输出结果
        print()
        print("=" * 60)
        print("  [OK] 密码重置成功!")
        print(f"     用户名: {username}")
        print(f"     新密码: {new_password}")
        print("=" * 60)
        print()
        print("  请立即使用新密码登录，并在[设置]页面中修改为您自己的密码。")
        print("  注意：如果服务正在运行，需要重启后新密码才会生效。")
        print()

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Reset Misaka MediaFlow admin password."
    )
    parser.add_argument(
        "username",
        nargs="?",
        default=ADMIN_USERNAME,
        help=f"要重置密码的用户名（默认: {ADMIN_USERNAME}）",
    )
    args = parser.parse_args()

    asyncio.run(reset_password(args.username))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()

