# src/services/p115/webhook_service.py
# Webhook 接收处理服务
#
# 支持来源：
#   1. CloudDrive2  POST /api/v1/webhook/cd2
#      body: { action: "create|delete|rename", is_dir, source_file, destination_file }
#   2. OpenList/通用 POST /api/v1/webhook/generic
#      body: { path, action, is_dir }  (宽松解析)
#
# 事件统一转换为内部格式后投入 life_monitor_service 的共享事件队列，
# 由监控服务统一去重、防抖、触发 STRM 同步。

import logging
import time

logger = logging.getLogger(__name__)

# CD2 action → 内部 event_action 映射
_CD2_ACTION_MAP = {
    "create": "create",
    "delete": "delete",
    "rename": "rename",   # rename 在 115 侧等同于 move
    "move":   "rename",
}


def parse_cd2_payload(payload: dict) -> list[dict]:
    """
    解析 CloudDrive2 file_system_watcher webhook body。

    CD2 body 结构：
    {
      "device_name": "...",
      "event_time": "1712000000",
      "data": [
        { "action": "create", "is_dir": "false",
          "source_file": "/影音/新剧集.mkv", "destination_file": "" }
      ]
    }

    返回标准化事件列表：
    [{ "source": "cd2", "action": "create"|"delete"|"rename",
       "is_dir": bool, "path": str, "dest_path": str, "time": int }]
    """
    events = []
    event_time = int(payload.get("event_time") or time.time())
    data_list = payload.get("data", [])
    if not isinstance(data_list, list):
        data_list = [data_list]

    for item in data_list:
        raw_action = (item.get("action") or "").lower()
        action = _CD2_ACTION_MAP.get(raw_action)
        if not action:
            logger.debug("[Webhook/CD2] 忽略未知 action=%s", raw_action)
            continue

        is_dir_raw = item.get("is_dir", "false")
        is_dir = str(is_dir_raw).lower() in ("true", "1", "yes")
        path = (item.get("source_file") or "").strip()
        dest = (item.get("destination_file") or "").strip()

        if not path:
            continue

        events.append({
            "source":    "cd2",
            "action":    action,
            "is_dir":    is_dir,
            "path":      path,
            "dest_path": dest,
            "time":      event_time,
        })
        logger.info("[Webhook/CD2] %s %s %s", action, "DIR" if is_dir else "FILE", path)

    return events


def parse_generic_payload(payload: dict) -> list[dict]:
    """
    解析通用 Webhook body（宽松格式，兼容 OpenList 等）。

    支持格式（任意一种均可）：
      { "path": "/影音/新剧集.mkv", "action": "create", "is_dir": false }
      { "file": "/影音/新剧集.mkv", "event": "upload" }
      { "changes": [{ "path": "...", "action": "..." }] }
    """
    events = []
    event_time = int(payload.get("time") or payload.get("event_time") or time.time())

    # 支持 changes 数组或单条
    items = payload.get("changes") or payload.get("data") or payload.get("events")
    if isinstance(items, list):
        raw_list = items
    else:
        raw_list = [payload]

    for item in raw_list:
        path = (item.get("path") or item.get("file") or item.get("source_file") or "").strip()
        if not path:
            continue

        raw_action = (item.get("action") or item.get("event") or "create").lower()
        # 宽松映射
        if raw_action in ("create", "upload", "add", "new"):
            action = "create"
        elif raw_action in ("delete", "remove", "del"):
            action = "delete"
        elif raw_action in ("rename", "move", "modify"):
            action = "rename"
        else:
            action = "create"  # 未知时默认视为新增

        is_dir_raw = item.get("is_dir", False)
        is_dir = str(is_dir_raw).lower() in ("true", "1", "yes") if isinstance(is_dir_raw, str) else bool(is_dir_raw)
        dest = (item.get("destination_file") or item.get("dest") or "").strip()

        events.append({
            "source":    "generic",
            "action":    action,
            "is_dir":    is_dir,
            "path":      path,
            "dest_path": dest,
            "time":      event_time,
        })
        logger.info("[Webhook/Generic] %s %s %s", action, "DIR" if is_dir else "FILE", path)

    return events
