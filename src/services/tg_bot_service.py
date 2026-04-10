# src/services/tg_bot_service.py
# Telegram Bot 服务 — 命令交互 + 入库/播放推送
#
# 功能：
#   1. 长轮询接收 Telegram 消息，支持命令：
#      /start     - 欢迎 + 功能列表
#      /status    - 系统状态概览
#      /playing   - 当前正在播放
#      /stats     - 媒体库统计
#      /search    - 搜索媒体库
#      /ol <link> - 115离线下载（TG转存）
#   2. 入库通知推送（生活事件监控回调）
#   3. 播放开始/停止推送（Emby Webhook 回调）
#
# 复用 notify_service 中的 telegram token/chat_id 配置
# 通过 SystemConfig 表存储 tg_bot_config

import asyncio
import json
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_TG_API = "https://api.telegram.org"
_bot_instance: Optional["TgBotService"] = None


def get_tg_bot() -> Optional["TgBotService"]:
    return _bot_instance


class TgBotService:
    """Telegram Bot 长轮询服务"""

    def __init__(self):
        self._token: str = ""
        self._chat_id: str = ""
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._offset = 0
        self._client: Optional[httpx.AsyncClient] = None
        self._handlers: dict = {}
        self._register_commands()

    def _register_commands(self):
        self._handlers = {
            "/start": self._cmd_start,
            "/help": self._cmd_start,
            "/status": self._cmd_status,
            "/playing": self._cmd_playing,
            "/stats": self._cmd_stats,
            "/search": self._cmd_search,
            "/ol": self._cmd_offline,
        }

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60)
        return self._client

    async def _api(self, method: str, **kwargs) -> dict:
        client = await self._ensure_client()
        url = f"{_TG_API}/bot{self._token}/{method}"
        resp = await client.post(url, json=kwargs)
        return resp.json() if resp.status_code == 200 else {}

    async def send_message(self, text: str, chat_id: str = "", parse_mode: str = "Markdown") -> bool:
        target = chat_id or self._chat_id
        if not target or not self._token:
            return False
        try:
            r = await self._api("sendMessage", chat_id=target, text=text, parse_mode=parse_mode)
            return r.get("ok", False)
        except Exception as e:
            logger.warning("[TgBot] 发送失败: %s", e)
            return False

    # ── 配置加载 ────────────────────────────────────────────────────
    async def load_config(self) -> bool:
        """从 notify_config 中读取 telegram token/chat_id"""
        try:
            from src.db import get_async_session_local
            from src.db.models import SystemConfig
            from sqlalchemy import select
            async with get_async_session_local() as db:
                row = await db.execute(select(SystemConfig).where(SystemConfig.key == "notify_config"))
                cfg = row.scalars().first()
                if cfg and cfg.value:
                    data = json.loads(cfg.value)
                    tg = data.get("telegram", {})
                    self._token = tg.get("token", "")
                    self._chat_id = tg.get("chat_id", "")
                    return bool(self._token)
        except Exception as e:
            logger.warning("[TgBot] 配置加载失败: %s", e)
        return False

    # ── 启动/停止 ───────────────────────────────────────────────────
    async def start(self):
        if self._running:
            return
        if not await self.load_config():
            logger.info("[TgBot] 未配置 token，跳过启动")
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("[TgBot] Bot 已启动，开始长轮询")

    async def stop(self):
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        logger.info("[TgBot] Bot 已停止")

    async def _poll_loop(self):
        """长轮询主循环"""
        while self._running:
            try:
                client = await self._ensure_client()
                url = f"{_TG_API}/bot{self._token}/getUpdates"
                resp = await client.post(url, json={
                    "offset": self._offset, "timeout": 30, "allowed_updates": ["message"]
                }, timeout=40)
                if resp.status_code != 200:
                    await asyncio.sleep(5)
                    continue
                data = resp.json()
                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    asyncio.create_task(self._handle_update(update))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[TgBot] 轮询异常: %s", e)

    # ── 消息处理 ────────────────────────────────────────────────────
    async def _handle_update(self, update: dict):
        msg = update.get("message", {})
        text = msg.get("text", "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if not text or not chat_id:
            return

        # 解析命令
        cmd = text.split()[0].split("@")[0].lower()
        args = text[len(cmd):].strip()

        handler = self._handlers.get(cmd)
        if handler:
            try:
                await handler(chat_id, args)
            except Exception as e:
                logger.error("[TgBot] 命令 %s 执行失败: %s", cmd, e, exc_info=True)
                await self.send_message(f"❌ 命令执行失败：{e}", chat_id)
        elif text.startswith("/"):
            await self.send_message("❓ 未知命令，发送 /help 查看帮助", chat_id)

    # ── 命令实现 ────────────────────────────────────────────────────
    async def _cmd_start(self, chat_id: str, args: str):
        text = (
            "🎬 *Misaka MediaFlow Bot*\n\n"
            "可用命令：\n"
            "📊 /status — 系统状态\n"
            "▶️ /playing — 当前播放\n"
            "📈 /stats — 媒体库统计\n"
            "🔍 /search <关键词> — 搜索媒体库\n"
            "⬇️ /ol <链接> — 115离线下载\n"
            "❓ /help — 帮助信息"
        )
        await self.send_message(text, chat_id)

    async def _cmd_status(self, chat_id: str, args: str):
        from src.services.media_server_service import media_server_service
        adapter = await media_server_service.get_adapter()
        if not adapter:
            await self.send_message("⚠️ 媒体服务器未连接", chat_id)
            return
        try:
            info = await adapter.get_system_info()
            sessions = await adapter.get_active_sessions()
            playing = [s for s in sessions if s.get("is_playing")]
            text = (
                f"🖥 *系统状态*\n"
                f"服务器：{info.get('ServerName', '-')}\n"
                f"版本：{info.get('Version', '-')}\n"
                f"系统：{info.get('OperatingSystemDisplayName', '-')}\n"
                f"活跃会话：{len(sessions)}\n"
                f"正在播放：{len(playing)}"
            )
            await self.send_message(text, chat_id)
        except Exception as e:
            await self.send_message(f"❌ 获取状态失败：{e}", chat_id)

    async def _cmd_playing(self, chat_id: str, args: str):
        from src.services.media_server_service import media_server_service
        adapter = await media_server_service.get_adapter()
        if not adapter:
            await self.send_message("⚠️ 媒体服务器未连接", chat_id)
            return
        sessions = await adapter.get_active_sessions()
        playing = [s for s in sessions if s.get("is_playing")]
        if not playing:
            await self.send_message("🎬 当前没有正在播放的内容", chat_id)
            return
        lines = ["▶️ *正在播放*\n"]
        for s in playing:
            np = s.get("now_playing", {})
            title = np.get("series_name", "")
            if title:
                title += f" - {np.get('name', '')}"
            else:
                title = np.get("name", "未知")
            method = s.get("play_state", {}).get("play_method", "")
            tag = "🟢直播" if method == "DirectPlay" else "🟠转码" if method == "Transcode" else "🔵串流"
            lines.append(f"• {title}\n  👤 {s['user_name']} | 📱 {s['client']} | {tag}")
        await self.send_message("\n".join(lines), chat_id)

    async def _cmd_stats(self, chat_id: str, args: str):
        from src.services.media_server_service import media_server_service
        adapter = await media_server_service.get_adapter()
        if not adapter:
            await self.send_message("⚠️ 媒体服务器未连接", chat_id)
            return
        counts = await adapter.get_item_counts()
        text = (
            f"📈 *媒体库统计*\n\n"
            f"🎬 电影：{counts.get('movie_count', 0)}\n"
            f"📺 剧集：{counts.get('series_count', 0)}\n"
            f"📼 单集：{counts.get('episode_count', 0)}\n"
            f"🎵 专辑：{counts.get('album_count', 0)}\n"
            f"🎶 歌曲：{counts.get('song_count', 0)}"
        )
        await self.send_message(text, chat_id)

    async def _cmd_search(self, chat_id: str, args: str):
        if not args:
            await self.send_message("用法：`/search 关键词`", chat_id)
            return
        from src.services.media_server_service import media_server_service
        adapter = await media_server_service.get_adapter()
        if not adapter:
            await self.send_message("⚠️ 媒体服务器未连接", chat_id)
            return
        try:
            client = await adapter._ensure_client()
            resp = await client.get("/emby/Items", params={
                "SearchTerm": args, "Recursive": "true", "Limit": 10,
                "IncludeItemTypes": "Movie,Series,Episode",
                "Fields": "ProductionYear",
            })
            data = resp.json() if resp.status_code == 200 else {}
            items = data.get("Items", [])
            if not items:
                await self.send_message(f"🔍 未找到「{args}」相关内容", chat_id)
                return
            lines = [f"🔍 *搜索「{args}」结果*\n"]
            for i in items[:10]:
                year = f" ({i.get('ProductionYear', '')})" if i.get('ProductionYear') else ""
                emoji = "🎬" if i.get("Type") == "Movie" else "📺" if i.get("Type") == "Series" else "📼"
                lines.append(f"{emoji} {i.get('Name', '')}{year}")
            await self.send_message("\n".join(lines), chat_id)
        except Exception as e:
            await self.send_message(f"❌ 搜索失败：{e}", chat_id)

    async def _cmd_offline(self, chat_id: str, args: str):
        if not args:
            await self.send_message("用法：`/ol <磁力链接或链接>`", chat_id)
            return
        await self.send_message(f"⏳ 正在提交离线下载...\n`{args[:60]}...`", chat_id)
        try:
            from src.adapters.storage.p115 import P115Manager
            mgr = P115Manager()
            if not mgr.enabled or not mgr.ready:
                await self.send_message("⚠️ 115 网盘未就绪", chat_id)
                return
            result = mgr.client.offline_add(args)
            if result:
                await self.send_message("✅ 离线下载任务已添加！\n文件将在下载完成后自动通过增量同步生成 STRM", chat_id)
            else:
                await self.send_message("❌ 离线下载添加失败", chat_id)
        except Exception as e:
            await self.send_message(f"❌ 离线下载失败：{e}", chat_id)

    # ── 主动推送（供外部调用）────────────────────────────────────────
    async def notify_playback_start(self, user: str, title: str, client: str):
        text = f"▶️ *播放开始*\n🎬 {title}\n👤 {user} | 📱 {client}"
        await self.send_message(text)

    async def notify_playback_stop(self, user: str, title: str):
        text = f"⏹ *播放停止*\n🎬 {title}\n👤 {user}"
        await self.send_message(text)

    async def notify_library_new(self, title: str, media_type: str = ""):
        emoji = "🎬" if media_type == "Movie" else "📺" if media_type == "Series" else "📼"
        text = f"📥 *新入库*\n{emoji} {title}"
        await self.send_message(text)


async def init_tg_bot():
    """应用启动时初始化 TG Bot"""
    global _bot_instance
    _bot_instance = TgBotService()
    await _bot_instance.start()


async def shutdown_tg_bot():
    """应用关闭时停止 TG Bot"""
    global _bot_instance
    if _bot_instance:
        await _bot_instance.stop()
        _bot_instance = None
