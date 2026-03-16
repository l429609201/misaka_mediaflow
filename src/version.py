# py-server/app/version.py — 版本号硬编码文件（与 main.py 同目录）
# 全项目唯一版本源（Single Source of Truth）

APP_NAME = "Misaka MediaFlow"
VERSION = "1.0.0"
VERSION_TAG = f"v{VERSION}"
BUILD_DATE = ""    # 构建时由 CI/CD 写入，本地开发为空
GIT_COMMIT = ""    # 构建时由 CI/CD 写入，本地开发为空

