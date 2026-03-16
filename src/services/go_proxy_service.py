# src/services/go_proxy_service.py
# Go 反代进程管理服务 — 独立模块，统一管理 Go 反代进程生命周期

import json
import logging
import subprocess
import sys
import threading
from pathlib import Path

from sqlalchemy import select

from src.core.config import settings
from src.db import get_async_session_local
from src.db.models import SystemConfig

logger = logging.getLogger(__name__)
_go_logger = logging.getLogger("go-proxy")

# ==================== 进程状态 ====================

_proc: subprocess.Popen | None = None
_log_thread: threading.Thread | None = None


# ==================== 内部工具 ====================

def _pipe_logs(proc: subprocess.Popen) -> None:
    """后台线程：逐行读取 Go 子进程 stdout，转发到 Python 日志系统"""
    try:
        for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                _go_logger.info(line)
    except Exception:
        pass


def _find_binary() -> str:
    """查找 Go 反代可执行文件路径"""
    project_root = Path(__file__).resolve().parent.parent.parent
    is_win = sys.platform == "win32"
    names = ["mediaflow-proxy", "go-proxy"]
    candidates = []
    for name in names:
        exe = f"{name}.exe" if is_win else name
        candidates.append(project_root / "proxy" / exe)
        candidates.append(project_root / "go-proxy" / exe)
        candidates.append(project_root / exe)
    for c in candidates:
        if c.exists():
            return str(c)
    return ""


# ==================== 公开 API ====================

def get_status() -> dict:
    """获取 Go 反代进程状态（同步方法，无需 await）"""
    global _proc
    running = _proc is not None and _proc.poll() is None
    binary = _find_binary()
    return {
        "running": running,
        "pid": _proc.pid if running else None,
        "binary_found": bool(binary),
        "binary_path": binary,
    }


async def start() -> dict:
    """启动 Go 反代进程"""
    global _proc, _log_thread

    if _proc and _proc.poll() is None:
        return {"success": True, "message": "已在运行中", "pid": _proc.pid}

    binary = _find_binary()
    if not binary:
        return {"success": False, "message": "未找到 Go 反代可执行文件，请将 go-proxy 放在 go-proxy/ 目录下"}

    # 从数据库读端口、Emby 地址、API Key
    go_port = settings.server.go_port
    emby_host = settings.media_server.host
    emby_apikey = settings.media_server.api_key

    async with get_async_session_local() as db:
        for key, attr in [
            ("proxy_go_port", "go_port"),
            ("media_server_host", "emby_host"),
            ("media_server_api_key", "emby_apikey"),
        ]:
            row = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
            cfg = row.scalars().first()
            if cfg and cfg.value:
                val = cfg.value.strip('"').strip()
                if attr == "go_port":
                    try:
                        go_port = int(json.loads(cfg.value))
                    except (ValueError, TypeError):
                        pass
                elif attr == "emby_host":
                    emby_host = val
                elif attr == "emby_apikey":
                    emby_apikey = val

    # 构建启动命令
    cmd = [binary, "--port", str(go_port)]
    if emby_host:
        cmd += ["--emby-host", emby_host]
    if emby_apikey:
        cmd += ["--emby-apikey", emby_apikey]

    try:
        _proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        _log_thread = threading.Thread(
            target=_pipe_logs, args=(_proc,), daemon=True
        )
        _log_thread.start()
        logger.info("Go 反代已启动: pid=%d port=%d emby=%s", _proc.pid, go_port, emby_host)
        return {"success": True, "pid": _proc.pid, "port": go_port}
    except Exception as e:
        logger.error("启动 Go 反代失败: %s", e)
        return {"success": False, "message": str(e)}


async def stop() -> dict:
    """停止 Go 反代进程"""
    global _proc

    if not _proc or _proc.poll() is not None:
        return {"success": True, "message": "进程未运行"}

    pid = _proc.pid
    try:
        _proc.terminate()
        _proc.wait(timeout=5)
    except Exception:
        _proc.kill()
    _proc = None
    logger.info("Go 反代已停止: pid=%d", pid)
    return {"success": True, "message": "已停止"}


def get_traffic() -> dict:
    """
    获取 Go 反代流量统计。
    尝试从 Go 反代的 HTTP API 读取，如果未运行或不支持则返回空数据。
    """
    global _proc
    if not _proc or _proc.poll() is not None:
        return {"available": False, "message": "Go 反代未运行"}

    import httpx

    # Go 反代端口：优先从启动命令中提取实际端口
    go_port = _get_running_port()
    try:
        resp = httpx.get(f"http://127.0.0.1:{go_port}/api/traffic", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            return {"available": True, **data}
    except Exception:
        pass

    return {
        "available": False,
        "message": "Go 反代流量接口暂不可用",
        "total_upload": 0,
        "total_download": 0,
        "current_upload": 0,
        "current_download": 0,
    }


def _get_running_port() -> int:
    """获取 Go 反代实际运行端口（从启动命令参数中解析）"""
    global _proc
    if _proc and _proc.poll() is None:
        try:
            args = _proc.args
            if isinstance(args, list) and "--port" in args:
                idx = args.index("--port")
                if idx + 1 < len(args):
                    return int(args[idx + 1])
        except (ValueError, IndexError, AttributeError):
            pass
    return settings.server.go_port

