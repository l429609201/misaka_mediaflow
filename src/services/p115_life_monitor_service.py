# src/services/p115_life_monitor_service.py
# 115 生活事件监控服务
#
# 参考实现：DDSRem-Dev/MoviePilot-Plugins p115strmhelper
#   helper/life/client.py → MonitorLife.once_pull / creata_strm / remove_strm
#
# 事件类型（对齐 p115strmhelper 注释）：
#   1  上传图片        → 生成 STRM
#   2  上传文件/目录   → 生成 STRM
#   5  移动图片        → 生成 STRM
#   6  移动文件/目录   → 生成 STRM
#   14 接收文件        → 生成 STRM
#   17 创建新目录      → 触发增量同步
#   18 复制文件夹      → 生成 STRM
#   22 删除文件/文件夹 → 仅记录（防误删）
#
# 接口选择（根据扫码时 login_app）：
#   web/desktop/harmony CK → life_list(app="web")  → life.115.com ✅
#   android/ios/alipaymini → iter_life_behavior_once(app=login_app) ✅
#
# 流控（对齐 p115strmhelper once_pull）：
#   cooldown=4s；失败重试 3 次，间隔 2s；无新事件等 20s；出错等 30s

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

def _parse_event_fields(raw: dict, raw_count: int) -> Optional[dict]:
    """
    从原始事件 dict 解析标准化字段。

    iter_life_behavior_once 返回字段（对齐 p115strmhelper）：
      type(int), id, update_time, file_name, file_id, parent_id,
      pick_code, file_category(0=目录), file_size, sha1

    life_list 接口返回字段：
      behavior_type(str 如"delete_file"), id, update_time, file_name,
      file_id, parent_id, pick_code 等（部分事件字段可能缺失）

    返回 None 表示事件不需要处理（不在触发类型内）。
    """
    # DEBUG 级别打印原始字段（对齐 p115strmhelper logger.debug 风格）
    logger.debug("【监控生活事件】原始事件 #%d keys=%s", raw_count, list(raw.keys()))
    logger.debug("【监控生活事件】原始事件 #%d data=%s", raw_count, raw)

    # 事件类型：iter_life_behavior_once 返回 type(int)；life_list 返回 behavior_type(str)
    raw_type  = raw.get("type") or raw.get("behavior_type")
    ev_type   = _parse_behavior_type(raw_type)
    ev_name   = _BEHAVIOR_TYPE_NAMES.get(ev_type, f"未知({ev_type})")

    # 文件名：标准字段 file_name，life_list 可能嵌套在 file_info 里
    file_info = raw.get("file_info") or {}
    file_name = (raw.get("file_name") or file_info.get("file_name")
                 or raw.get("file_name_show") or raw.get("fn") or raw.get("n") or "")

    # 文件 ID
    file_id   = str(raw.get("file_id") or file_info.get("file_id")
                    or raw.get("fid") or raw.get("file_id_str") or "")

    # 父目录 ID
    parent_id = str(raw.get("parent_id") or file_info.get("parent_id")
                    or raw.get("pid") or raw.get("category_id") or "")

    # pickcode：iter_life_behavior_once 用 pick_code；life_list 可能用 pickcode 或 pc
    pick_code = (raw.get("pick_code") or file_info.get("pick_code")
                 or raw.get("pickcode") or raw.get("pc") or "")

    # 时间戳和事件 ID
    up_time   = int(raw.get("update_time") or raw.get("time") or 0)
    ev_id     = int(raw.get("id") or raw.get("event_id") or 0)

    # file_category：0=目录，非0=文件（iter_life_behavior_once 标准字段）
    file_category = raw.get("file_category", -1)

    if ev_type not in _SYNC_TRIGGER_TYPES:
        logger.debug("【监控生活事件】忽略事件类型 %d(%s): %s", ev_type, ev_name, file_name)
        return None

    return {
        "type":          ev_type,
        "type_name":     ev_name,
        "file_name":     file_name,
        "file_id":       file_id,
        "parent_id":     parent_id,
        "pick_code":     pick_code,
        "time":          up_time,
        "event_id":      ev_id,
        "file_category": file_category,  # 0=目录, 非0=文件, -1=未知
    }


def _sync_fetch_life_events(p115_client, from_time: int, from_id: int,
                             login_app: str = "web") -> Optional[list]:
    """
    根据扫码时选择的 login_app 类型，选择对应的生活事件接口。
    返回 None 表示请求异常需重试；返回 [] 表示无新事件。
    """
    import time as _time
    _WEB_APPS = {"", "web", "desktop", "harmony"}
    logger.debug("【监控生活事件】接口分发 login_app=%s from_time=%d from_id=%d",
                 login_app, from_time, from_id)
    if login_app in _WEB_APPS:
        return _fetch_via_life_list(p115_client, from_time, from_id, _time)
    else:
        return _fetch_via_behavior_once(p115_client, from_time, from_id, login_app, _time)


def _fetch_via_life_list(p115_client, from_time: int, from_id: int, _time) -> Optional[list]:
    """web CK 专用：life.115.com/life_list（接受 SSOENT=A）"""
    events: list = []
    raw_count = 0
    offset = 0
    limit = 100
    cooldown = 4
    page_num = 0
    try:
        while True:
            page_num += 1
            payload = {"show_type": 0, "limit": limit, "start": offset}
            logger.debug("【监控生活事件】life_list 第%d页 offset=%d", page_num, offset)
            resp = p115_client.life_list(payload, app="web")
            if not isinstance(resp, dict):
                logger.warning("【监控生活事件】life_list 返回非 dict: %s", type(resp))
                return None
            if not resp.get("state"):
                logger.warning("【监控生活事件】life_list state=False errno=%s error=%s",
                               resp.get("errno"), resp.get("error"))
                return None
            data = resp.get("data", {})
            page_list = data.get("list", [])
            total = int(data.get("count", 0))
            logger.debug("【监控生活事件】life_list 第%d页: total=%d 本页=%d条",
                         page_num, total, len(page_list))
            stop_flag = False
            for raw in page_list:
                raw_count += 1
                ev_id_raw = int(raw.get("id") or 0)
                up_time   = int(raw.get("update_time") or raw.get("time") or 0)
                if from_id and ev_id_raw and ev_id_raw <= from_id:
                    stop_flag = True
                    break
                if from_time and up_time and up_time < from_time:
                    stop_flag = True
                    break
                parsed = _parse_event_fields(raw, raw_count)
                if parsed is not None:
                    events.append(parsed)
            if stop_flag:
                break
            offset += len(page_list)
            if not page_list or offset >= total:
                break
            _time.sleep(cooldown)
        logger.debug("【监控生活事件】life_list 完毕: %d页 原始%d条 触发%d条",
                     page_num, raw_count, len(events))
        return events
    except Exception as e:
        logger.warning("【监控生活事件】life_list 异常: %s", e, exc_info=True)
        return None


def _fetch_via_behavior_once(p115_client, from_time: int, from_id: int,
                              login_app: str, _time) -> Optional[list]:
    """非 web CK 专用：iter_life_behavior_once(app=login_app)，对齐 p115strmhelper once_pull"""
    try:
        from p115client.tool.life import iter_life_behavior_once
    except ImportError:
        logger.warning("【监控生活事件】p115client.tool.life 不可用，降级到 life_list")
        return _fetch_via_life_list(p115_client, from_time, from_id, _time)
    events: list = []
    raw_count = 0
    try:
        logger.debug("【监控生活事件】behavior_once app=%s from_time=%d from_id=%d",
                     login_app, from_time, from_id)
        for event in iter_life_behavior_once(
            client=p115_client,
            from_time=from_time,
            from_id=from_id,
            cooldown=4,
            app=login_app,
        ):
            raw_count += 1
            parsed = _parse_event_fields(event, raw_count)
            if parsed is not None:
                events.append(parsed)
        logger.debug("【监控生活事件】behavior_once 完毕: 原始%d条 触发%d条", raw_count, len(events))
        return events
    except Exception as e:
        logger.warning("【监控生活事件】behavior_once(app=%s) 异常: %s", login_app, e, exc_info=True)
        return None


def _sync_get_parent_path(p115_client, parent_id: str) -> str:
    """
    通过 parent_id 查询父目录路径。
    参考 p115strmhelper MonitorLife._get_path_by_cid：
      先尝试 client.fs_info（ID 反查路径）。
    若都失败，返回空字符串（降级到只写 STRM 根目录）。
    """
    if not p115_client or not parent_id or parent_id == "0":
        return ""
    try:
        resp = p115_client.fs_info({"file_id": int(parent_id)})
        if resp and resp.get("state"):
            # fs_info 返回 path 字段（完整路径）
            data = resp.get("data", [])
            if data:
                paths = [item.get("file_name", "") for item in data]
                return "/" + "/".join(p for p in paths if p)
    except Exception as e:
        logger.debug("【监控生活事件】fs_info 查询父目录失败 parent_id=%s: %s", parent_id, e)
    return ""


def _sync_write_single_strm(
    p115_client,
    pick_code: str,
    file_name: str,
    parent_id: str,
    cloud_path: str,
    strm_root: Path,
    link_host: str,
    url_tmpl: str,
    video_exts: set,
) -> str:
    """
    精确为单个文件生成 STRM。

    对齐 p115strmhelper MonitorLife.creata_strm 的单文件处理逻辑：
      1. 校验 pick_code 格式（17位纯字母数字）
      2. 校验文件扩展名是否为视频
      3. 用 parent_id 查父目录路径 + 拼接 file_name 得到完整云盘路径
         （p115strmhelper: _get_path_by_cid(parent_id) + file_name）
      4. 检查路径是否在配置的 cloud_path 监控范围内
      5. 计算相对路径 → 生成 STRM 文件

    返回 "created" / "skipped" / "out_of_scope" / "error"
    """
    # ① 校验视频扩展名
    ext = Path(file_name).suffix.lstrip(".").lower()
    if ext not in video_exts:
        logger.debug("【监控生活事件】跳过非视频文件: %s", file_name)
        return "out_of_scope"

    # ② 校验 pick_code（参考 p115strmhelper: 17位纯字母数字）
    if not pick_code:
        logger.error("【监控生活事件】%s 不存在 pick_code 值，无法生成 STRM 文件", file_name)
        return "error"
    if not (len(pick_code) == 17 and pick_code.isalnum()):
        logger.error("【监控生活事件】错误的 pick_code 值 %s，无法生成 STRM 文件", pick_code)
        return "error"

    # ③ 查父目录路径 + 拼接文件名，得到完整云盘路径
    #    对齐 p115strmhelper: dir_path = _get_path_by_cid(parent_id)
    #                         file_path = Path(dir_path) / file_name
    parent_dir = _sync_get_parent_path(p115_client, parent_id)
    if parent_dir:
        item_path = (parent_dir.rstrip("/") + "/" + file_name)
    else:
        item_path = ""
        logger.debug("【监控生活事件】无法获取父目录路径 parent_id=%s，将放置于STRM根目录: %s",
                     parent_id, file_name)

    logger.debug(
        "【监控生活事件】解析路径: file=%r parent_id=%s parent_dir=%r → item_path=%r",
        file_name, parent_id, parent_dir, item_path,
    )

    # ④ 检查路径是否在监控范围内
    cloud_root = "/" + cloud_path.strip("/")
    if item_path:
        norm_path = "/" + item_path.strip("/")
        if not norm_path.startswith(cloud_root + "/") and norm_path != cloud_root:
            logger.debug("【监控生活事件】路径不在监控范围 cloud_root=%s: %s",
                         cloud_root, norm_path)
            return "out_of_scope"
        # 计算相对于 cloud_root 的目录
        parent_norm = str(Path(norm_path).parent)
        try:
            rel_dir = Path(parent_norm).relative_to(cloud_root)
        except ValueError:
            rel_dir = Path(".")
    else:
        # 无法确定路径 → 放置于 STRM 根目录（宁可写入，不漏掉）
        rel_dir = Path(".")

    # ⑤ 渲染 STRM URL
    from src.services.p115_strm_sync_service import P115StrmSyncService
    strm_content = P115StrmSyncService._render_strm_url(
        url_tmpl, link_host, pick_code, file_name, item_path
    )

    # ⑥ 写 STRM 文件（对齐 p115strmhelper creata_strm 写入逻辑）
    try:
        strm_dir = strm_root / rel_dir
        strm_dir.mkdir(parents=True, exist_ok=True)
        strm_file = strm_dir / Path(file_name).with_suffix(".strm").name

        if strm_file.exists():
            existing = strm_file.read_text(encoding="utf-8").strip()
            if existing == strm_content.strip():
                logger.debug("【监控生活事件】STRM 文件已存在且内容相同，跳过: %s", strm_file)
                return "skipped"
            logger.debug("【监控生活事件】STRM 文件内容变更，覆盖: %s", strm_file)

        strm_file.write_text(strm_content, encoding="utf-8")
        # 对齐 p115strmhelper 日志格式：【监控生活事件】生成 STRM 文件成功: {path}
        logger.info("【监控生活事件】生成 STRM 文件成功: %s", str(strm_file))
        return "created"
    except Exception as e:
        logger.error("【监控生活事件】%s 生成 STRM 文件失败: %s", file_name, e)
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
        主轮询循环，参考 p115strmhelper monitor_life_thread_worker + once_pull 的结构：
          - 有新事件：处理完立即开始下一轮（不额外等待）
          - 无新事件：等待 20 秒（参考 p115strmhelper once_pull stop_event.wait(20)）
          - 出现异常：等待 30 秒（参考 p115strmhelper "30s 后尝试重新启动"）
          - poll_interval：用户配置的最小轮询间隔（默认 30 秒，有事件时不生效）
        """
        self._running = True
        logger.info(
            "【监控生活事件】监控已启动 from_time=%d from_id=%d",
            self._last_event_time, self._last_event_id,
        )

        try:
            while True:
                wait_secs = 20  # 默认：无新事件等 20 秒（对齐 p115strmhelper）
                try:
                    config = await self.get_config()
                    # 用户配置的 poll_interval 作为无新事件时的等待下限
                    poll_interval = max(10, config.get("poll_interval", 30))

                    logger.debug(
                        "【监控生活事件】开始本轮轮询 from_time=%d from_id=%d",
                        self._last_event_time, self._last_event_id,
                    )
                    new_events = await self._poll_once()

                    if new_events:
                        logger.info("【监控生活事件】本轮收到 %d 条新事件，开始处理", len(new_events))
                        await self._handle_events(new_events, config)
                        # 有新事件：处理完立即开始下一轮，不等待
                        wait_secs = 0
                    else:
                        # 无新事件：等待 max(20, poll_interval) 秒
                        wait_secs = max(20, poll_interval)
                        logger.debug("【监控生活事件】本轮无新事件，%ds 后再次轮询", wait_secs)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("【监控生活事件】轮询异常: %s", e, exc_info=True)
                    wait_secs = 30
                    logger.info("【监控生活事件】%ds 后重试", wait_secs)

                if wait_secs > 0:
                    await asyncio.sleep(wait_secs)

        except asyncio.CancelledError:
            logger.info("【监控生活事件】监控已停止")
        finally:
            self._running = False

    async def _poll_once(self) -> list:
        """
        拉取本轮新事件。
        根据扫码时选择的 login_app 自动选择接口：
          - web CK → life_list(web)
          - android/ios/alipaymini CK → iter_life_behavior_once(app=login_app)
        带 3 次重试（参考 p115strmhelper once_pull），失败等待 2 秒。
        """
        manager = _get_manager()
        if not manager.enabled or not manager.ready:
            logger.debug("【监控生活事件】115 未启用或未就绪，跳过本轮")
            return []

        p115_client = manager.adapter._get_p115_client()
        if p115_client is None:
            logger.debug("【监控生活事件】p115_client 不可用，跳过本轮")
            return []

        # 读取登录时的 app 类型（决定走哪个接口）
        login_app = getattr(manager.adapter._auth, "login_app", "web") or "web"
        logger.debug("【监控生活事件】本轮使用 login_app=%s", login_app)

        # 重试机制（参考 p115strmhelper once_pull: 3 次重试，失败等 2 秒）
        events = None
        max_retries = 3
        for attempt in range(max_retries, -1, -1):
            try:
                events = await asyncio.to_thread(
                    _sync_fetch_life_events,
                    p115_client,
                    self._last_event_time,
                    self._last_event_id,
                    login_app,
                )
                if events is not None:
                    break  # 成功（包括空列表 []）
            except Exception as e:
                if attempt <= 0:
                    logger.error("【监控生活事件】拉取数据失败（重试已耗尽）: %s", e)
                    return []
                logger.warning(
                    "【监控生活事件】拉取数据失败，剩余重试 %d 次: %s", attempt, e
                )
                await asyncio.sleep(2)

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
                "【监控生活事件】更新基准 from_time: %d→%d  from_id: %d→%d",
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
        link_host   = strm_svc._get_link_host(strm_config)
        url_tmpl    = await strm_svc._get_url_template()

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
                "【监控生活事件】%s %s %s",
                type_name, file_name, f"(file_id={file_id} parent_id={parent_id} pick={pick_code})",
            )
            self._add_event_log(ev)

            # 删除事件：只记录，不删 STRM（防误删，对齐 p115strmhelper remove_strm 需要数据库支撑）
            if ev_type == 22:
                logger.info("【监控生活事件】删除事件（仅记录，暂不删除 STRM）: %s", file_name)
                continue

            # 目录操作：回退到增量同步
            if ev_type in _DIR_OP_TYPES:
                logger.info("【监控生活事件】目录操作事件，标记兜底增量同步: %s", file_name)
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
                    pick_code,
                    file_name,
                    parent_id,
                    cloud_path,
                    Path(strm_root_str),
                    link_host,
                    url_tmpl,
                    video_exts,
                )
                logger.debug(
                    "【监控生活事件】rule_cloud=%s result=%s file=%s",
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
                    "【监控生活事件】%s 不在任何监控范围或处理失败，标记兜底增量同步", file_name
                )
                need_inc_sync = True

        logger.info("【监控生活事件】本轮处理完毕 created=%d skipped=%d out_of_scope=%d errors=%d need_inc_sync=%s",
                    stats["created"], stats["skipped"], stats["out_of_scope"], stats["errors"], need_inc_sync)

        if need_inc_sync and config.get("auto_inc_sync", True):
            result = await strm_svc.trigger_inc_sync()
            logger.info("【监控生活事件】触发兜底增量同步: %s", result)

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

