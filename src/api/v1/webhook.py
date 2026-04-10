# src/api/v1/webhook.py
# Webhook 接收接口
#
# 路由：
#   POST /api/v1/webhook/cd2      接收 CloudDrive2 file_system_watcher 推送
#   POST /api/v1/webhook/generic  接收 OpenList / 自定义 Webhook 推送
#   GET  /api/v1/webhook/status   查询 Webhook 接收统计状态

import logging
import time

from fastapi import APIRouter, Request

router = APIRouter(prefix="/webhook", tags=["Webhook 接收"])

logger = logging.getLogger(__name__)

# 内存统计（重启清零）
_stats = {
    "cd2_total":     0,
    "generic_total": 0,
    "last_received": 0,
    "last_source":   "",
}


def _get_monitor():
    from src.services.p115.life_monitor_service import get_life_monitor_service
    return get_life_monitor_service()


async def _verify_token(request: Request, configured_token: str) -> bool:
    """验证 Webhook Token（配置为空则跳过验证）"""
    if not configured_token:
        return True
    # 支持 Header Authorization: Bearer <token> 或 X-Webhook-Token: <token>
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() == configured_token
    token_header = request.headers.get("x-webhook-token", "")
    if token_header:
        return token_header.strip() == configured_token
    # URL 参数兜底
    token_param = request.query_params.get("token", "")
    return token_param == configured_token


@router.post("/cd2")
async def receive_cd2_webhook(request: Request):
    """
    接收 CloudDrive2 file_system_watcher Webhook 推送。

    CD2 配置（webhook.toml）：
      [file_system_watcher]
      url = "{base_url}/api/v1/webhook/cd2"
      enabled = true
    """
    from src.services.p115.webhook_service import parse_cd2_payload

    try:
        payload = await request.json()
    except Exception:
        logger.warning("[Webhook/CD2] 请求体解析失败，非 JSON")
        return {"success": False, "message": "invalid json"}

    # 验证 Token
    monitor = _get_monitor()
    cfg = await monitor.get_config()
    webhook_token = cfg.get("webhook_token", "")
    if not await _verify_token(request, webhook_token):
        logger.warning("[Webhook/CD2] Token 验证失败，拒绝请求")
        return {"success": False, "message": "unauthorized"}

    events = parse_cd2_payload(payload)
    _stats["cd2_total"] += len(events)
    _stats["last_received"] = int(time.time())
    _stats["last_source"] = "cd2"

    if events:
        await monitor.receive_webhook_events(events)

    logger.info("[Webhook/CD2] 收到 %d 条事件（payload keys=%s）",
                len(events), list(payload.keys()))
    return {"success": True, "received": len(events)}


@router.post("/generic")
async def receive_generic_webhook(request: Request):
    """
    接收通用 Webhook 推送（OpenList、自定义脚本等）。

    支持宽松 JSON 格式：
      { "path": "/影音/新剧集.mkv", "action": "create", "is_dir": false }
    """
    from src.services.p115.webhook_service import parse_generic_payload

    try:
        payload = await request.json()
    except Exception:
        logger.warning("[Webhook/Generic] 请求体解析失败")
        return {"success": False, "message": "invalid json"}

    monitor = _get_monitor()
    cfg = await monitor.get_config()
    webhook_token = cfg.get("webhook_token", "")
    if not await _verify_token(request, webhook_token):
        logger.warning("[Webhook/Generic] Token 验证失败")
        return {"success": False, "message": "unauthorized"}

    events = parse_generic_payload(payload)
    _stats["generic_total"] += len(events)
    _stats["last_received"] = int(time.time())
    _stats["last_source"] = "generic"

    if events:
        await monitor.receive_webhook_events(events)

    logger.info("[Webhook/Generic] 收到 %d 条事件", len(events))
    return {"success": True, "received": len(events)}


@router.get("/status")
async def webhook_status():
    """查询 Webhook 接收统计（无需认证，供监控面板轮询）"""
    return {
        "cd2_total":     _stats["cd2_total"],
        "generic_total": _stats["generic_total"],
        "last_received": _stats["last_received"],
        "last_source":   _stats["last_source"],
    }



# ── Emby 同步删除 Webhook ─────────────────────────────────────────────

@router.post("/emby")
async def receive_emby_webhook(request: Request):
    """
    接收 Emby Webhook 推送（主要处理删除事件）
    Emby 设置 → Webhook → URL: {base_url}/api/v1/webhook/emby
    """
    try:
        payload = await request.json()
    except Exception:
        logger.warning("[Webhook/Emby] 请求体解析失败")
        return {"success": False, "message": "invalid json"}

    event_type = payload.get("Event", "")
    _stats["last_received"] = int(time.time())
    _stats["last_source"] = f"emby:{event_type}"

    # 仅处理删除事件
    if event_type in ("library.deleted", "item.remove"):
        from src.services.p115.enhancements import sync_delete_by_emby_webhook
        result = await sync_delete_by_emby_webhook(payload)
        logger.info("[Webhook/Emby] 同步删除处理: %s", result)
        return {"success": True, **result}

    logger.debug("[Webhook/Emby] 事件 %s 不处理", event_type)
    return {"success": True, "skipped": True, "event": event_type}


@router.get("/sync-del/history")
async def get_sync_del_history():
    """获取同步删除历史"""
    from src.services.p115.enhancements import get_sync_del_history
    return {"history": get_sync_del_history()}


@router.post("/sync-del/clear")
async def clear_sync_del_history_api():
    """清空同步删除历史"""
    from src.services.p115.enhancements import clear_sync_del_history
    count = clear_sync_del_history()
    return {"success": True, "cleared": count}
