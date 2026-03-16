# app/core/config.py
# 配置系统 — pydantic-settings 驱动
# 优先级: 环境变量(MISAKAMF_ 前缀) > config.yaml > 默认值
# 对齐 misaka_danmu_server 项目配置风格

import os
import logging
from pathlib import Path
from typing import Any, Dict, Tuple, Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

logger = logging.getLogger(__name__)

# ==================== 工作目录 ====================
# 默认工作目录为 ./config（与弹幕库项目一致）
# 可通过 MISAKAMF_CONFIG_DIR 环境变量覆盖
CONFIG_DIR = Path(os.getenv("MISAKAMF_CONFIG_DIR", "./config"))
CONFIG_FILE = CONFIG_DIR / "config.yaml"
LOG_DIR = CONFIG_DIR / "logs"


# ==================== 子配置模型 ====================

class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 7789               # 主服务端口
    go_port: int = 9906            # Go 反代端口
    log_level: str = "info"
    external_url: str = ""


class DatabaseConfig(BaseModel):
    type: str = "postgresql"       # postgresql / mysql
    host: str = "127.0.0.1"
    port: int = 5432
    name: str = "mediaflow"
    user: str = "mediaflow"
    password: str = ""
    pool_size: int = 10
    max_overflow: int = 20
    # URL 构建统一在 src/db/database.py 中用 URL.create() 处理


class RedisConfig(BaseModel):
    enabled: bool = False          # 默认不启用，使用内存缓存
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0
    password: str = ""
    key_prefix: str = "mmf:"


class MediaServerConfig(BaseModel):
    type: str = "emby"             # emby / jellyfin
    host: str = "http://127.0.0.1:8096"
    api_key: str = ""


class ProxyConfig(BaseModel):
    cache_ttl: int = 900
    mem_cache_size: int = 10000
    connect_timeout: int = 10
    ws_ping_interval: int = 30


class SecurityConfig(BaseModel):
    api_token: str = ""
    admin_password: str = ""


class AdminConfig(BaseModel):
    initial_user: Optional[str] = None
    initial_password: Optional[str] = None


# ==================== 运行时配置（不在模板中暴露，通过环境变量或配置文件高级设置） ====================

class StrmConfig(BaseModel):
    output_dir: str = "./config/strm"
    mode: str = "proxy"            # proxy / direct / alist / p115 / p115_path
    workers: int = 4
    cron: str = "0 3 * * *"


class P115OpenApiConfig(BaseModel):
    access_token: str = ""
    refresh_token: str = ""


class P115RateLimitConfig(BaseModel):
    download_url_interval: float = 1.5
    waf_cooldown: float = 10.0


class P115Config(BaseModel):
    enabled: bool = True
    cookie: str = ""
    openapi: P115OpenApiConfig = P115OpenApiConfig()
    rate_limit: P115RateLimitConfig = P115RateLimitConfig()
    link_cache_ttl: int = 7200
    mounts: list = []


class ClientFilterConfig(BaseModel):
    enabled: bool = False
    ua_blacklist: list = []


# ==================== YAML 配置源 ====================

class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """从 config.yaml 加载配置的自定义 Source"""

    def get_field_value(
        self, field: Any, field_name: str
    ) -> Tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> Dict[str, Any]:
        if not CONFIG_FILE.exists():
            return {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data
        except Exception as e:
            logger.warning(f"读取配置文件失败: {e}")
            return {}


# ==================== 配置文件模板生成 ====================

_CONFIG_TEMPLATE = """\
# ===========================================
# Misaka MediaFlow 配置文件
# 自动生成 - 请根据实际情况修改
#
# 优先级: 环境变量(MISAKAMF_前缀) > 本文件 > 默认值
# 环境变量格式: MISAKAMF_SERVER__PORT=7789
# ===========================================

# 服务器
server:
  host: "0.0.0.0"
  port: 7789                       # 主服务端口
  go_port: 9906                    # Go 反代端口
  log_level: "info"                # debug / info / warning / error
  # external_url: ""               # 外部访问地址

# 时区
timezone: "Asia/Shanghai"

# 数据库
database:
  type: "postgresql"               # postgresql / mysql
  host: "127.0.0.1"
  port: 5432
  name: "mediaflow"
  user: "mediaflow"
  password: ""

# Redis (默认不启用，使用内存缓存)
redis:
  enabled: false                   # 设为 true 启用 Redis
  host: "127.0.0.1"
  port: 6379
  db: 0
  password: ""

# 媒体服务器
media_server:
  type: "emby"                     # emby / jellyfin
  host: "http://127.0.0.1:8096"
  api_key: ""

# 反代参数
proxy:
  cache_ttl: 900
  mem_cache_size: 10000
  connect_timeout: 10
  ws_ping_interval: 30

# 安全
security:
  api_token: ""                    # 留空则自动生成
  # admin_password: ""             # 留空则首次启动自动生成随机密码
"""


def ensure_config_file():
    """确保 config 目录和配置文件存在，不存在则自动生成"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
        logger.info(f"配置文件已自动生成: {CONFIG_FILE}")


# ==================== 主配置类 ====================

class Settings(BaseSettings):
    """
    全局配置
    优先级: 环境变量 > config.yaml > 默认值
    """
    server: ServerConfig = ServerConfig()
    timezone: str = "Asia/Shanghai"
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    media_server: MediaServerConfig = MediaServerConfig()
    proxy: ProxyConfig = ProxyConfig()
    security: SecurityConfig = SecurityConfig()
    admin: AdminConfig = AdminConfig()
    strm: StrmConfig = StrmConfig()
    p115: P115Config = P115Config()
    client_filter: ClientFilterConfig = ClientFilterConfig()

    model_config = {
        "env_prefix": "MISAKAMF_",
        "env_nested_delimiter": "__",
        "extra": "ignore",
    }

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls),
        )


def load_settings() -> Settings:
    """加载配置（确保配置文件存在后再加载）"""
    ensure_config_file()
    return Settings()


# 全局单例
settings = load_settings()
