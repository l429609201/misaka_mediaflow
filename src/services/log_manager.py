# src/services/log_manager.py
# 日志管理模块 — 对齐 misaka_danmu_server/src/services/log_manager.py
# main.py 只需调用 setup_logging() 即可完成全部日志初始化

import collections
import logging
import logging.handlers
import asyncio
import re
from pathlib import Path
from typing import List, Set

from src.core.config import settings, LOG_DIR

# ==================== 内存日志队列（供 Web UI 实时查看） ====================

_logs_deque = collections.deque(maxlen=200)
_log_subscribers: Set[asyncio.Queue] = set()


class DequeHandler(logging.Handler):
    """将日志写入内存双端队列，同时通知所有 SSE 订阅者"""

    def __init__(self, deque):
        super().__init__()
        self.deque = deque

    def emit(self, record):
        log_message = self.format(record)
        self.deque.appendleft(log_message)
        for queue in _log_subscribers:
            try:
                queue.put_nowait(log_message)
            except asyncio.QueueFull:
                pass


# ==================== 日志过滤器 ====================

class SensitiveInfoFilter(logging.Filter):
    """隐藏日志中的敏感信息（API Key、Token 等）"""
    PATTERNS = [
        (re.compile(r'(api_key=)([a-zA-Z0-9]{16,})'), r'\1****'),
        (re.compile(r'(apikey=)([a-zA-Z0-9]{16,})'), r'\1****'),
        (re.compile(r'(token=)([a-zA-Z0-9_-]{16,})'), r'\1****'),
        (re.compile(r'(Authorization:\s*Bearer\s+)([a-zA-Z0-9_.-]{16,})'), r'\1****'),
        (re.compile(r'(password["\s:=]+)([^\s,;"]{4,})'), r'\1****'),
    ]

    def filter(self, record):
        msg = record.getMessage()
        for pattern, replacement in self.PATTERNS:
            msg = pattern.sub(replacement, msg)
        record.msg = msg
        record.args = ()
        return True


class NoHttpxLogFilter(logging.Filter):
    """从 UI 日志中排除 httpx 的日志"""
    def filter(self, record):
        return not record.name.startswith('httpx')


# ==================== setup_logging ====================

def setup_logging():
    """
    配置根日志记录器：控制台 + 可轮转文件 + 内存队列。
    应在 lifespan 启动时调用一次。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "misaka-mediaflow.log"
    go_log_file = LOG_DIR / "go-proxy.log"

    log_level = getattr(logging, settings.server.log_level.upper(), logging.INFO)

    verbose_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    ui_formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # 使用 "src" logger（不是 root），避免 uvicorn reload 时重复
    src_logger = logging.getLogger("src")
    src_logger.setLevel(log_level)
    src_logger.propagate = False

    # 清理已存在的 handler，防止热重载时重复
    if src_logger.hasHandlers():
        src_logger.handlers.clear()

    # 全局过滤器
    src_logger.addFilter(SensitiveInfoFilter())

    # 1. 控制台 — Docker 容器日志始终全量 DEBUG，方便 `docker logs` 查看全链路
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(verbose_formatter)
    src_logger.addHandler(console_handler)

    # 2. 文件（可轮转）— 始终写入 DEBUG 全量日志，前端按级别过滤展示
    file_handler = logging.handlers.RotatingFileHandler(
        str(log_file), maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8',
    )
    file_handler.setLevel(logging.DEBUG)   # ← 固定 DEBUG，写全量
    file_handler.setFormatter(verbose_formatter)
    src_logger.addHandler(file_handler)

    # 3. 内存队列（供 Web UI 实时查看）
    # ⚠️ 始终设为 DEBUG，让全量日志进队列；前端按级别过滤显示
    deque_handler = DequeHandler(_logs_deque)
    deque_handler.setLevel(logging.DEBUG)
    deque_handler.addFilter(NoHttpxLogFilter())
    deque_handler.setFormatter(ui_formatter)
    src_logger.addHandler(deque_handler)

    # src_logger 本身也需要 DEBUG，才能让 DEBUG 日志流过来
    src_logger.setLevel(logging.DEBUG)

    # ==================== Go 反代日志 ====================
    # go-proxy logger: 写独立日志文件 + 共享控制台 + 共享内存队列
    go_logger = logging.getLogger("go-proxy")
    go_logger.setLevel(logging.DEBUG)
    go_logger.propagate = False

    if go_logger.hasHandlers():
        go_logger.handlers.clear()

    # Go 独立日志文件（可轮转）
    go_file_handler = logging.handlers.RotatingFileHandler(
        str(go_log_file), maxBytes=10 * 1024 * 1024, backupCount=3, encoding='utf-8',
    )
    go_file_handler.setLevel(logging.DEBUG)
    go_file_handler.setFormatter(verbose_formatter)
    go_logger.addHandler(go_file_handler)

    # Go 日志也输出到控制台 — 同样全量 DEBUG
    go_console_handler = logging.StreamHandler()
    go_console_handler.setLevel(logging.DEBUG)
    go_console_handler.setFormatter(verbose_formatter)
    go_logger.addHandler(go_console_handler)

    # Go 日志也进内存队列（Web UI 可以看到）
    go_deque_handler = DequeHandler(_logs_deque)
    go_deque_handler.setLevel(logging.DEBUG)
    go_deque_handler.setFormatter(ui_formatter)
    go_logger.addHandler(go_deque_handler)

    logging.getLogger("src").info(
        f"日志系统已初始化 (目录: {LOG_DIR})\n"
        f"  - {log_file.name} (主日志)\n"
        f"  - {go_log_file.name} (Go反代日志)"
    )


# ==================== 工具函数 ====================

def get_logs() -> List[str]:
    """返回内存队列中的日志条目（最新在前）"""
    return list(_logs_deque)


def get_log_dir() -> Path:
    """返回日志目录路径"""
    return LOG_DIR


def list_log_files() -> List[dict]:
    """列出日志目录中的所有日志文件"""
    log_dir = get_log_dir()
    if not log_dir.exists():
        return []
    pattern = re.compile(r'^.+\.log(\.\d+)?$')
    files = []
    for f in sorted(log_dir.iterdir()):
        if f.is_file() and pattern.match(f.name):
            stat = f.stat()
            files.append({"name": f.name, "size": stat.st_size, "modified": stat.st_mtime})
    files.sort(key=lambda x: x["modified"], reverse=True)
    return files


def read_log_file(filename: str, tail: int = 500) -> List[str]:
    """读取指定日志文件的最后 N 行"""
    log_dir = get_log_dir()
    file_path = (log_dir / filename).resolve()
    if not str(file_path).startswith(str(log_dir.resolve())):
        raise ValueError("非法的文件路径")
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"日志文件不存在: {filename}")
    from collections import deque as _deque
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = list(_deque(f, maxlen=tail))
    return [line.rstrip('\n').rstrip('\r') for line in lines]


def subscribe_to_logs(queue: asyncio.Queue) -> None:
    """订阅日志更新（SSE 推送用）"""
    _log_subscribers.add(queue)


def unsubscribe_from_logs(queue: asyncio.Queue) -> None:
    """取消订阅日志更新"""
    _log_subscribers.discard(queue)

