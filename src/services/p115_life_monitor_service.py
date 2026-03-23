# src/services/p115_life_monitor_service.py
# 115 生活事件监控服务
#
# 核心设计参考（精确对齐参考实现）：
#
# ① DDSRem-Dev/MoviePilot-Plugins p115strmhelper
#    helper/life/client.py  → MonitorLife（事件拉取 + 精确处理单文件）
#    service/life/__init__.py → monitor_life_thread_worker（轮询主循环）
#    关键 API：
#      from p115client.tool.life import iter_life_behavior_once, life_show
#      iter_life_behavior_once(client, from_time, from_id, cooldown=4, app="ios")
#    关键字段：event["behavior_type"] / event["file_name"] / event["file_id"]
#              event["parent_id"] / event["pick_code"] / event["update_time"]
#
# ② hbq0405/emby-toolkit
#    p115client 直接调用 life_show，逐页拉取事件，mtime 过滤
#
# 核心流程（参考 p115strmhelper MonitorLife.once_pull）：
#   1. iter_life_behavior_once(client, from_time=last_ts, from_id=last_id, app="ios")
#      → 拉取上次 from_time/from_id 之后的所有新事件（once = 不阻塞，消费完即止）
#   2. 对每条事件：
#      - 打印 DEBUG 日志（type / file_name / parent_id / pick_code）
#      - 过滤只处理 _SYNC_TRIGGER_TYPES
#      - 检查 file_id 对应的云盘路径是否在配置的监控 cloud_path 内
#      - 命中 → 精确为该单文件生成 STRM（不触发全量/增量扫描）
#      - 目录操作/无法精确定位 → 兜底触发增量同步
#      - 记录本轮最大 (update_time, event_id) 用于下次 from_time/from_id
#   3. 若无新事件，等待 poll_interval 秒后再次拉取
#
# 为什么不触发增量同步？
#   增量同步按 from_time 过滤 mtime，有时差风险（刚上传的文件 mtime≈now≤from_time）；
#   精确处理单文件：直接拿事件里的 pick_code + 路径写 .strm，零延迟、零误判。

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from src.db import get_async_session_local
from src.db.models.system import SystemConfig
from sqlalchemy import select

logger = logging.getLogger(__name__)

_MONITOR_CONFIG_KEY = "p115_life_monitor_config"

# 需要触发 STRM 操作的事件类型（对齐 p115strmhelper _SYNC_TRIGGER_TYPES）
_SYNC_TRIGGER_TYPES = {1, 2, 5, 6, 14, 17, 18, 22}

# 仅需触发增量同步（目录操作）的类型 —— 无法精确定位单文件时回退
_DIR_OP_TYPES = {17, 18}  # 创建新目录、复制文件夹

# 视频扩展名
_DEFAULT_VIDEO_EXTS = {"mp4", "mkv", "avi", "ts", "iso", "mov", "m2ts", "rmvb", "flv", "wmv", "m4v"}

# 事件类型中文名（对应 p115client.tool.life.BEHAVIOR_TYPE_TO_NAME）
_BEHAVIOR_TYPE_NAMES = {
    1:  "上传图片",
    2:  "上传文件/目录",
    3:  "标星图片",
    4:  "标星文件/目录",
    5:  "移动图片",
    6:  "移动文件/目录",
    7:  "浏览图片",
    8:  "浏览视频",
    9:  "浏览音频",
    10: "浏览文档",
    14: "接收文件",
    17: "创建新目录",
    18: "复制文件夹",
    19: "标签文件夹",
    20: "重命名文件夹",
    22: "删除文件/文件夹",
}

# webapi 返回的字符串类型名 → 数字类型映射
# （115 webapi behavior_type 字段返回字符串，p115client 返回数字，需要兼容）
_BEHAVIOR_STR_TO_INT = {
    "upload_image_file": 1,
    "upload_file":       2,
    "star_image":        3,
    "star_file":         4,
    "move_image_file":   5,
    "move_file":         6,
    "browse_image":      7,
    "browse_video":      8,
    "browse_audio":      9,
    "browse_document":   10,
    "receive_files":     14,
    "new_folder":        17,
    "copy_folder":       18,
    "folder_label":      19,
    "folder_rename":     20,
    "delete_file":       22,
}


def _get_manager():
    from src.adapters.storage.p115 import P115Manager
    return P115Manager()


def _parse_behavior_type(raw) -> int:
    """
    将 behavior_type 统一转为 int。
    - p115client 接口返回数字（int）
    - 115 webapi life_list 返回字符串（如 "delete_file"）
    - 未知类型返回 -1
    """
    if raw is None:
        return -1
    if isinstance(raw, int):
        return raw
    # 先尝试直接转 int（"2" → 2）
    try:
        return int(raw)
    except (ValueError, TypeError):
        pass
    # 再查字符串映射表
    return _BEHAVIOR_STR_TO_INT.get(str(raw), -1)


# ─────────────────────────────────────────────────────────────────────────────
# 同步拉取函数（在 asyncio.to_thread 中运行，避免阻塞事件循环）
# ─────────────────────────────────────────────────────────────────────────────

def _sync_fetch_life_events(p115_client, from_time: int, from_id: int) -> Optional[list]:
    """
    用 p115client.tool.life.iter_life_behavior_once 拉取生活事件。

    "once" 语义：消费完当前队列即返回，不会永久阻塞。

    参考 p115strmhelper helper/life/client.py MonitorLife.once_pull：
      iter_life_behavior_once(client, from_time, from_id, cooldown=4, app="ios")

    关键：不传 app 参数（使用默认），避免 iOS cookie 与当前 web/android cookie 不匹配
    导致 P115LoginError（/ios/behavior/detail 接口要求 iOS cookie）。

    返回 None 表示 p115client 不可用需要 webapi 回退；返回 [] 表示无新事件。
    """
    try:
        from p115client.tool.life import iter_life_behavior_once
    except ImportError:
        logger.debug("[生活事件] p115client.tool.life 不可用，将使用 webapi 回退")
        return None

    events = []
    try:
        logger.debug("[生活事件] iter_life_behavior_once 开始拉取 from_time=%d from_id=%d",
                     from_time, from_id)
        raw_count = 0
        for event in iter_life_behavior_once(
            client=p115_client,
            from_time=from_time,
            from_id=from_id,
            cooldown=4,
            # 不传 app 参数：使用 p115client 默认（web），避免 iOS cookie 不匹配问题
            # 日志中错误路径 /ios/behavior/detail 说明 app="ios" 会强制用 iOS 接口
        ):
            raw_count += 1
            # p115client 返回的事件字段（来自 p115client/tool/life.py 源码）：
            #   "type"        → 数字 int（如 2），是主字段
            #   "event_name"  → p115client 自动加的行为名字符串（如 "upload_file"）
            #   "file_id"     → 文件 ID 字符串
            #   "file_name"   → 文件名（部分事件可能没有）
            #   "parent_id"   → 父目录 ID
            #   "pick_code"/"pc" → pickcode
            #   "update_time" → 时间戳（部分事件可能没有）
            #   "id"          → 事件 ID 字符串
            # webapi life_list 返回的是 "behavior_type"（字符串），通过 _parse_behavior_type 兼容
            raw_type  = event.get("type") or event.get("behavior_type")
            ev_type   = _parse_behavior_type(raw_type)
            # p115client 自动注入的行为名，可直接用于日志
            ev_name   = (event.get("event_name")
                         or _BEHAVIOR_TYPE_NAMES.get(ev_type, f"未知({ev_type})"))
            file_name = (event.get("file_name") or event.get("file_name_show")
                         or event.get("fn") or "")
            file_id   = str(event.get("file_id") or event.get("fid") or "")
            parent_id = str(event.get("parent_id") or event.get("pid") or "")
            pick_code = (event.get("pick_code") or event.get("pickcode")
                         or event.get("pc") or "")
            up_time   = int(event.get("update_time") or event.get("time") or 0)
            ev_id     = int(event.get("id") or event.get("event_id") or 0)

            logger.debug(
                "[生活事件] 原始事件 #%d: type=%d(%s) file=%r "
                "file_id=%s parent_id=%s pick=%s time=%d ev_id=%d",
                raw_count, ev_type, ev_name,
                file_name, file_id, parent_id, pick_code, up_time, ev_id,
            )

            if ev_type not in _SYNC_TRIGGER_TYPES:
                logger.debug("[生活事件] 忽略事件类型 %d(%s)", ev_type, ev_name)
                continue

            events.append({
                "type":      ev_type,
                "type_name": ev_name,
                "file_name": file_name,
                "file_id":   file_id,
                "parent_id": parent_id,
                "pick_code": pick_code,
                "time":      up_time,
                "event_id":  ev_id,
            })

        logger.debug(
            "[生活事件] iter_life_behavior_once 拉取完毕: 原始 %d 条，触发类型 %d 条",
            raw_count, len(events),
        )
    except Exception as e:
        logger.warning("[生活事件] iter_life_behavior_once 异常: %s", e, exc_info=True)
        return None

    return events


def _sync_fetch_life_events_webapi(cookie: str, ua: str, from_time: int) -> Optional[list]:
    """
    回退方案：直接调用 115 life_list webapi，参考 emby-toolkit 的实现。
    """
    try:
        import httpx
    except ImportError:
        try:
            import requests as httpx  # type: ignore
        except ImportError:
            logger.debug("[生活事件] httpx/requests 均不可用，webapi 回退失败")
            return None

    events = []
    try:
        headers = {
            "Cookie": cookie,
            "User-Agent": ua or "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://115.com/",
        }
        resp = httpx.get(
            "https://life.115.com/api/1.0/web/1.0/life/life_list",
            headers=headers,
            params={"show_type": "0", "start": "0", "limit": "100"},
            timeout=15,
        )
        data = resp.json()
        logger.debug("[生活事件] webapi life_list 返回: state=%s", data.get("state"))

        for item in data.get("data", {}).get("list", []):
            # behavior_type 在 webapi 中是字符串（如 "delete_file"），用 _parse_behavior_type 转换
            raw_type = item.get("behavior_type") or item.get("type")
            ev_type  = _parse_behavior_type(raw_type)
            up_time  = int(item.get("update_time") or item.get("time") or 0)

            if up_time <= from_time:
                logger.debug("[生活事件] webapi 跳过旧事件 time=%d <= from_time=%d type=%d",
                             up_time, from_time, ev_type)
                continue

            file_name = item.get("file_name") or item.get("fn", "")
            file_id   = str(item.get("file_id") or item.get("fid") or "")
            parent_id = str(item.get("parent_id") or item.get("pid") or "")
            pick_code = item.get("pick_code") or item.get("pc", "")
            ev_id     = int(item.get("id") or 0)

            logger.debug(
                "[生活事件] webapi 事件: type=%d(%s) file=%r file_id=%s parent_id=%s",
                ev_type, _BEHAVIOR_TYPE_NAMES.get(ev_type, "?"),
                file_name, file_id, parent_id,
            )

            if ev_type not in _SYNC_TRIGGER_TYPES:
                continue

            events.append({
                "type":      ev_type,
                "type_name": _BEHAVIOR_TYPE_NAMES.get(ev_type, f"未知({ev_type})"),
                "file_name": file_name,
                "file_id":   file_id,
                "parent_id": parent_id,
                "pick_code": pick_code,
                "time":      up_time,
                "event_id":  ev_id,
            })
    except Exception as e:
        logger.warning("[生活事件] webapi 回退异常: %s", e, exc_info=True)
        return None

    return events


def _sync_write_single_strm(
    p115_client,
    file_id: str,
    pick_code: str,
    file_name: str,
    cloud_path: str,
    strm_root: Path,
    link_host: str,
    video_exts: set,
) -> str:
    """
    精确为单个文件生成 STRM（参考 p115strmhelper 对单事件的精确处理）。

    步骤：
    1. 检查文件扩展名是否是视频
    2. 用 p115client.tool.attr.get_path 查询该文件在 115 的完整路径
    3. 检查路径是否在 cloud_path 监控范围内
    4. 在 strm_root 下对应目录写入 .strm 文件

    返回 "created" / "skipped" / "out_of_scope" / "error"
    """
    ext = Path(file_name).suffix.lstrip(".").lower()
    if ext not in video_exts:
        logger.debug("[生活事件→STRM] 跳过非视频文件: %s", file_name)
        return "out_of_scope"

    if not pick_code:
        logger.warning("[生活事件→STRM] 缺少 pick_code，无法生成 STRM: %s", file_name)
        return "error"

    # 参考 p115strmhelper: pickcode 必须是 17 位纯字母数字
    if not (len(pick_code) == 17 and pick_code.isalnum()):
        logger.warning("[生活事件→STRM] pick_code 格式无效(%r)，跳过: %s", pick_code, file_name)
        return "error"

    # 查询完整路径（p115client.tool.attr.get_path）
    item_path = ""
    if p115_client is not None and file_id:
        try:
            from p115client.tool.attr import get_path
            item_path = get_path(p115_client, int(file_id))
            logger.debug("[生活事件→STRM] 查询路径: file_id=%s → %r", file_id, item_path)
        except Exception as e:
            logger.debug("[生活事件→STRM] get_path 失败 file_id=%s: %s", file_id, e)

    # 检查路径是否在监控范围内
    cloud_root = "/" + cloud_path.strip("/")
    if item_path:
        norm_path = "/" + str(item_path).strip("/")
        if not norm_path.startswith(cloud_root):
            logger.debug("[生活事件→STRM] 路径不在监控范围 cloud_root=%s: %s",
                         cloud_root, norm_path)
            return "out_of_scope"
        parent = str(Path(norm_path).parent)
        try:
            rel_dir = Path(parent).relative_to(cloud_root)
        except ValueError:
            rel_dir = Path(".")
    else:
        rel_dir = Path(".")
        logger.debug("[生活事件→STRM] 无法获取路径，文件放置于 STRM 根目录: %s", file_name)

    # 写 STRM 文件
    try:
        strm_dir = strm_root / rel_dir
        strm_dir.mkdir(parents=True, exist_ok=True)
        strm_file = strm_dir / Path(file_name).with_suffix(".strm").name
        strm_content = f"{link_host}/p115/play/{pick_code}/{file_name}"

        if strm_file.exists():
            existing = strm_file.read_text(encoding="utf-8").strip()
            if existing == strm_content.strip():
                logger.debug("[生活事件→STRM] 已存在且内容相同，跳过: %s", strm_file)
                return "skipped"
            logger.debug("[生活事件→STRM] 内容变更，覆盖: %s", strm_file)
        else:
            logger.debug("[生活事件→STRM] 新建: %s", strm_file)

        strm_file.write_text(strm_content, encoding="utf-8")
        logger.info("[生活事件→STRM] 已生成: %s → %s", file_name, strm_file)
        return "created"
    except Exception as e:
        logger.error("[生活事件→STRM] 写入失败 %s: %s", file_name, e)
        return "error"


# ─────────────────────────────────────────────────────────────────────────────
# 主服务类
# ─────────────────────────────────────────────────────────────────────────────

class P115LifeMonitorService:
    """115 生活事件监控服务"""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # 启动时以当前时间戳为基准，只处理此后产生的新事件
        self._last_event_time: int = int(time.time())
        # 上次已处理事件的最大 ID（避免重复处理同一时间戳内的事件）
        self._last_event_id: int = 0
        # 最近事件日志（UI 展示用）
        self._event_log: list = []

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def get_config(self) -> dict:
        defaults = {
            "enabled":       False,
            "poll_interval": 30,
            "auto_inc_sync": True,
        }
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _MONITOR_CONFIG_KEY)
            )
            cfg = result.scalars().first()
            if cfg and cfg.value:
                try:
                    return {**defaults, **json.loads(cfg.value)}
                except Exception:
                    pass
        return defaults

    async def save_config(self, config: dict) -> bool:
        from src.core.timezone import tm
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _MONITOR_CONFIG_KEY)
            )
            cfg = result.scalars().first()
            value = json.dumps(config, ensure_ascii=False)
            if cfg:
                cfg.value = value
                cfg.updated_at = tm.now()
            else:
                cfg = SystemConfig(
                    key=_MONITOR_CONFIG_KEY,
                    value=value,
                    description="115 生活事件监控配置",
                )
                db.add(cfg)
            await db.commit()
        return True

    def get_status(self) -> dict:
        return {
            "running":         self.is_running,
            "last_event_time": self._last_event_time,
            "last_event_id":   self._last_event_id,
            "recent_events":   self._event_log[-20:],
        }

    async def start(self) -> dict:
        if self.is_running:
            return {"success": False, "message": "监控已在运行中"}
        self._task = asyncio.create_task(self._monitor_loop())
        return {"success": True, "message": "生活事件监控已启动"}

    async def stop(self) -> dict:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._running = False
        return {"success": True, "message": "生活事件监控已停止"}

    async def _monitor_loop(self):
        """
        主轮询循环，参考 p115strmhelper monitor_life_thread_worker 的结构：
          while True:
              events = once_pull(from_time, from_id)
              for event in events:
                  handle_event(event)
              sleep(poll_interval)
        """
        self._running = True
        logger.info(
            "[生活事件] 监控已启动 from_time=%d from_id=%d",
            self._last_event_time, self._last_event_id,
        )

        try:
            while True:
                try:
                    config = await self.get_config()
                    poll_interval = max(10, config.get("poll_interval", 30))

                    logger.debug(
                        "[生活事件] 开始本轮轮询 from_time=%d from_id=%d",
                        self._last_event_time, self._last_event_id,
                    )
                    new_events = await self._poll_once()

                    if new_events:
                        logger.info("[生活事件] 本轮收到 %d 条新事件，开始处理", len(new_events))
                        await self._handle_events(new_events, config)
                    else:
                        logger.debug("[生活事件] 本轮无新事件，%ds 后再次轮询", poll_interval)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("[生活事件] 轮询异常: %s", e, exc_info=True)
                    poll_interval = 30

                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            logger.info("[生活事件] 监控已停止")
        finally:
            self._running = False

    async def _poll_once(self) -> list:
        """
        拉取本轮新事件，优先 p115client.tool.life，回退 webapi。
        拉取成功后更新 _last_event_time / _last_event_id。
        """
        manager = _get_manager()
        if not manager.enabled or not manager.ready:
            logger.debug("[生活事件] 115 未启用或未就绪，跳过本轮")
            return []

        p115_client = manager.adapter._get_p115_client()

        # ── 方案A：p115client iter_life_behavior_once ─────────────────────
        if p115_client is not None:
            events = await asyncio.to_thread(
                _sync_fetch_life_events,
                p115_client,
                self._last_event_time,
                self._last_event_id,
            )
        else:
            events = None
            logger.debug("[生活事件] p115_client 不可用，使用 webapi 回退")

        # ── 方案B：webapi 回退 ────────────────────────────────────────────
        if events is None:
            try:
                auth = manager.adapter._auth
                if not getattr(auth, "has_cookie", False):
                    logger.debug("[生活事件] 无 cookie，跳过 webapi 回退")
                    return []
                cookie = auth.cookie
                ua = auth.get_cookie_headers().get("User-Agent", "")
            except Exception as e:
                logger.debug("[生活事件] 获取 auth 失败: %s", e)
                return []

            events = await asyncio.to_thread(
                _sync_fetch_life_events_webapi,
                cookie, ua,
                self._last_event_time,
            )

        if not events:
            return []

        # 更新基准：取本轮最大 (time, event_id)
        max_time = max(ev["time"] for ev in events)
        max_id   = max(
            (ev.get("event_id", 0) for ev in events if ev["time"] == max_time),
            default=0,
        )
        if max_time > self._last_event_time or (
            max_time == self._last_event_time and max_id > self._last_event_id
        ):
            logger.debug(
                "[生活事件] 更新基准 from_time: %d→%d  from_id: %d→%d",
                self._last_event_time, max_time,
                self._last_event_id,   max_id,
            )
            self._last_event_time = max_time
            self._last_event_id   = max_id

        return events

    async def _handle_events(self, events: list, config: dict):
        """
        对每条事件精确处理（参考 p115strmhelper MonitorLife 的单文件处理策略）：
        - 上传/移动/接收 单文件事件 → 直接写 STRM，零延迟
        - 目录操作（创建/复制目录）  → 触发增量同步（无法精确定位文件）
        - 删除事件                  → 记录日志，不删 STRM（防误删）
        """
        manager = _get_manager()
        p115_client = manager.adapter._get_p115_client() if manager.ready else None

        from src.services.p115_strm_sync_service import P115StrmSyncService
        strm_svc    = P115StrmSyncService()
        strm_config = await strm_svc.get_config()
        sync_rules  = strm_config.get("sync_rules", [])
        video_exts  = set(strm_config.get("video_exts", list(_DEFAULT_VIDEO_EXTS)))
        link_host   = strm_config.get("link_host", "").rstrip("/")

        need_inc_sync = False
        stats = {"created": 0, "skipped": 0, "out_of_scope": 0, "errors": 0}

        for ev in events:
            ev_type   = ev["type"]
            file_name = ev["file_name"]
            file_id   = ev["file_id"]
            parent_id = ev["parent_id"]
            pick_code = ev["pick_code"]
            type_name = ev["type_name"]

            logger.info(
                "[生活事件] ▶ [%s] file=%r file_id=%s parent_id=%s pick=%s",
                type_name, file_name, file_id, parent_id, pick_code,
            )
            self._add_event_log(ev)

            # 删除事件：只记录，不删 STRM（防误删）
            if ev_type == 22:
                logger.info("[生活事件] 删除事件（仅记录，不删除 STRM）: %s", file_name)
                continue

            # 目录操作：回退到增量同步
            if ev_type in _DIR_OP_TYPES:
                logger.info("[生活事件] 目录操作事件，标记兜底增量同步: %s", file_name)
                need_inc_sync = True
                continue

            # 精确处理单文件：遍历所有同步规则
            handled = False
            for rule in sync_rules:
                cloud_path    = rule.get("cloud_path", "").strip().strip("/")
                strm_root_str = rule.get("strm_root", "").strip()
                if not cloud_path or not strm_root_str:
                    continue

                result = await asyncio.to_thread(
                    _sync_write_single_strm,
                    p115_client,
                    file_id,
                    pick_code,
                    file_name,
                    cloud_path,
                    Path(strm_root_str),
                    link_host,
                    video_exts,
                )
                logger.debug(
                    "[生活事件→STRM] rule_cloud=%s result=%s file=%s",
                    cloud_path, result, file_name,
                )

                if result == "created":
                    stats["created"] += 1
                    handled = True
                    break
                elif result == "skipped":
                    stats["skipped"] += 1
                    handled = True
                    break
                elif result == "out_of_scope":
                    stats["out_of_scope"] += 1
                elif result == "error":
                    stats["errors"] += 1
                    handled = True
                    break

            if not handled:
                logger.info(
                    "[生活事件] 文件不在任何监控范围或处理失败，标记兜底增量同步: %s", file_name
                )
                need_inc_sync = True

        logger.info("[生活事件] 本轮处理完毕 stats=%s need_inc_sync=%s", stats, need_inc_sync)

        if need_inc_sync and config.get("auto_inc_sync", True):
            result = await strm_svc.trigger_inc_sync()
            logger.info("[生活事件] 触发兜底增量同步: %s", result)

    def _add_event_log(self, event: dict):
        """添加事件到日志（最多保留 100 条）"""
        self._event_log.append(event)
        if len(self._event_log) > 100:
            self._event_log = self._event_log[-100:]


# ─────────────────────────────────────────────────────────────────────────────
# 全局单例
# ─────────────────────────────────────────────────────────────────────────────

_life_monitor_service: Optional[P115LifeMonitorService] = None


def get_life_monitor_service() -> P115LifeMonitorService:
    global _life_monitor_service
    if _life_monitor_service is None:
        _life_monitor_service = P115LifeMonitorService()
    return _life_monitor_service

