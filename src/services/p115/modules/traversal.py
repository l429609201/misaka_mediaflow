# src/services/p115/modules/traversal.py
# 遍历模块
# 负责 115 网盘目录树遍历和 STRM 文件生成的核心逻辑。
# 所有函数为普通同步函数（在 asyncio.to_thread 中执行），或 async 函数（调用 DB）。
#
#   两阶段设计：
#   阶段一：从网盘拉取完整目录树到内存（唯一调用网盘 API 的阶段）
#     - 方案1: iter_files_with_path_skim（非 web CK，一次请求，最快）
#     - 方案2: iter_files_with_path    （所有 CK，库封装递归+内置冷却）
#     - 方案3: iterdir 手动递归        （最终 fallback）
#   阶段二：本地对比 + 写入（零网盘 API 调用）
#     - 扫描本地 STRM 目录，与云盘列表对比
#     - 按 overwrite_mode 决定新建/跳过/覆盖
#     - 无论结果如何，都写 FsCache + StrmFile（供文件列表页显示）

import asyncio
import logging
import time
from pathlib import Path

from src.services.p115.modules.strm_writer import (
    calc_rel_path, get_strm_filename, render_strm_url,
)
from src.services.p115.modules.db_ops import lookup_cid_by_path

logger = logging.getLogger(__name__)

# ── 405 WAF 冷却相关常量 ─────────────────────────────────────────────────────
# 115 API 返回 405 时表示 IP 被 WAF 临时屏蔽，需要较长冷却时间
_405_COOLDOWN_BASE    = 30.0    # 首次 405 冷却秒数
_405_COOLDOWN_MAX     = 300.0   # 最大冷却秒数
_405_COOLDOWN_FACTOR  = 2.0     # 指数退避倍数
_405_MAX_RETRIES      = 6       # 405 最大重试次数（普通错误仍然 3 次）
_NORMAL_MAX_RETRIES   = 3       # 普通错误最大重试次数


def _is_405_error(exc: Exception) -> bool:
    """
    判断异常是否为 HTTP 405（115 WAF 屏蔽）。
    多层检测保证兼容不同版本的 p115client 异常包装。
    """
    # 1. 检查 code 属性（p115client 自定义异常通常有 code 字段）
    #    注意：code 可能是 int 也可能是 str
    code = getattr(exc, "code", None)
    if code is not None:
        try:
            if int(code) == 405:
                return True
        except (TypeError, ValueError):
            pass

    # 2. 检查 response 对象的 status_code（httpx / requests 风格）
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if status is None:
            # ResponseWrapper 有时叫 .status
            status = getattr(response, "status", None)
        try:
            if int(status) == 405:
                return True
        except (TypeError, ValueError):
            pass

    # 3. 检查 str(exc) 是否包含 405 / Method Not Allowed
    err_str = str(exc)
    if "405" in err_str or "Method Not Allowed" in err_str:
        return True

    # 4. 递归检查异常链（__cause__ / __context__）
    for chained in (getattr(exc, "__cause__", None), getattr(exc, "__context__", None)):
        if chained is not None and chained is not exc:
            if _is_405_error(chained):
                return True

    return False

# ── iOS UA（参考 p115strmhelper get_ios_ua_app，走 proapi.115.com 规避405风控）──
_IOS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.53(0x18003531) NetType/WIFI Language/zh_CN"
)

# web 类型 CK 不支持 skim（走 /os_windows 接口，web CK 返回 errno=99）
_WEB_APPS_SET = {"", "web", "desktop", "harmony"}


def iter_and_write_strm(
    manager,
    cid: str,
    cloud_path: str,
    strm_root: Path,
    video_exts: set,
    link_host: str,
    url_tmpl: str = "",
    from_time: int = 0,
    overwrite_mode: str = "skip",
    api_interval: float = 1.0,
    fscache_tree: dict | None = None,
) -> tuple[dict, list[dict], list[dict]]:
    """
    两阶段遍历：
      阶段一：从网盘拉取整棵目录树到内存列表（唯一调用网盘 API 的阶段）
      阶段二：扫本地 STRM、对比、写文件、写缓存（零网盘 API 调用）

    返回 (stats, fscache_batch, strmfile_batch)：
      stats          — {"created": N, "skipped": N, "errors": N}
      fscache_batch  — 所有云盘条目（目录+文件），写入 P115FsCache
      strmfile_batch — 所有视频文件（含 skip），写入 StrmFile 供列表页显示
    """
    stats: dict = {"created": 0, "skipped": 0, "errors": 0}
    fscache_batch: list[dict] = []
    strmfile_batch: list[dict] = []

    p115_client = manager.adapter._get_p115_client()
    if p115_client is None:
        logger.error("p115_client 不可用，无法同步")
        return stats, fscache_batch, strmfile_batch

    cloud_path_full = "/" + cloud_path.strip("/")

    logger.debug(
        "入参: cid=%r cloud_path=%r strm_root=%r "
        "from_time=%d overwrite_mode=%r api_interval=%.1f",
        cid, cloud_path, str(strm_root), from_time, overwrite_mode, api_interval,
    )

    # ══════════════════════════════════════════════════════════════════════
    # 阶段一：拉取网盘目录树 → cloud_items 内存列表
    # 这是整个流程唯一调用网盘 API 的阶段
    # ══════════════════════════════════════════════════════════════════════

    # ── 导入 p115client 工具函数 ──────────────────────────────────────────
    _fn_skim:    object = None
    _fn_iwp:     object = None
    _fn_iterdir: object = None
    has_skim: bool = False
    has_iwp:  bool = False
    try:
        from p115client.tool.iterdir import (  # type: ignore[import]
            iter_files_with_path_skim as _skim,
            iter_files_with_path      as _iwp,
            iterdir                   as _iterdir,
        )
        _fn_skim    = _skim
        _fn_iwp     = _iwp
        _fn_iterdir = _iterdir
        has_skim = True
        has_iwp  = True
    except ImportError:
        try:
            from p115client.tool.iterdir import (  # type: ignore[import]
                iter_files_with_path as _iwp,
                iterdir              as _iterdir,
            )
            _fn_iwp     = _iwp
            _fn_iterdir = _iterdir
            has_iwp  = True
            logger.debug("iter_files_with_path_skim 不可用，将使用 iter_files_with_path")
        except ImportError:
            try:
                from p115client.tool.iterdir import iterdir as _iterdir_fn  # type: ignore[import] as _iterdir  # type: ignore[import]
                _fn_iterdir = _iterdir
                logger.debug("仅 iterdir 可用，将使用手动递归")
            except ImportError:
                logger.error("p115client.tool.iterdir 不可用")
                return stats, fscache_batch, strmfile_batch

    # ── 判断 CK 类型 ──────────────────────────────────────────────────────
    login_app_raw = getattr(getattr(manager.adapter, "_auth", None), "login_app", "") or ""
    iter_app_for_skim = "web" if login_app_raw in _WEB_APPS_SET else login_app_raw
    skim_usable = has_skim and (login_app_raw not in _WEB_APPS_SET)
    iter_app    = "web" if login_app_raw in _WEB_APPS_SET else login_app_raw
    logger.debug("CK类型: login_app=%r skim_usable=%s", login_app_raw, skim_usable)

    # cloud_items: 收集所有原始条目（含目录，用于 FsCache）
    # cloud_files: 只含视频文件候选（供阶段二对比）
    cloud_items: list[dict] = []   # 所有条目（文件+目录）
    cloud_files: list[dict] = []   # 仅文件条目（含 item_path 字段）

    def _collect_item(item: dict, item_path: str) -> None:
        """把云盘条目收入内存列表（不做任何本地 IO / 网盘 API 调用）"""
        d = dict(item)
        d["_item_path"] = item_path   # 注入完整路径，供阶段二使用
        cloud_items.append(d)
        if not d.get("is_dir"):
            cloud_files.append(d)

    fetched = False   # 是否已成功拉取到数据

    # ── 方案一：iter_files_with_path_skim（非 web CK，一次请求）──────────
    if has_skim and skim_usable and _fn_skim is not None:
        logger.info(
            "【阶段一】skim 拉取云盘树: cid=%s cloud_path=%r app=%s",
            cid, cloud_path, iter_app_for_skim,
        )
        try:
            iter_kwargs: dict = {"cid": int(cid), "app": iter_app_for_skim}
            if iter_app_for_skim not in _WEB_APPS_SET:
                iter_kwargs["headers"] = {"user-agent": _IOS_UA}
            first = True
            for item in _fn_skim(p115_client, **iter_kwargs):  # type: ignore[operator]
                if first:
                    logger.debug("skim 首条字段: %s", list(dict(item).keys()))
                    first = False
                ip = item.get("path") or cloud_path_full + "/" + item.get("name", "")
                _collect_item(dict(item), ip)
            logger.info("【阶段一】skim 完成，共收集 %d 条目", len(cloud_items))
            fetched = True
        except Exception as e:
            if _is_405_error(e):
                logger.warning("skim 遭遇 405，冷却 %.0fs 后降级: %s", _405_COOLDOWN_BASE, e)
                time.sleep(_405_COOLDOWN_BASE)
            else:
                logger.warning("skim 失败，降级: %s", e, exc_info=True)

    # ── 方案二：iter_files_with_path（非 web CK，库封装递归）────────────
    # 注意：iter_files_with_path 内部同样会调用 /os_windows 接口，
    # web CK 使用该接口会返回 errno=99，因此 web CK 也必须跳过方案二，直接走方案三。
    if not fetched and has_iwp and _fn_iwp is not None and skim_usable:
        reason = "skim 失败"
        logger.info(
            "【阶段一】iter_files_with_path 拉取云盘树: cid=%s (%s) iter_app=%s cooldown=%.1f",
            cid, reason, iter_app, api_interval,
        )
        try:
            first = True
            for item in _fn_iwp(  # type: ignore[operator]
                p115_client,
                cid=int(cid),
                type=99,
                cur=0,
                escape=None,
                app=iter_app,
                cooldown=api_interval,
            ):
                if first:
                    logger.debug("iwp 首条字段: %s",
                                 [k for k in dict(item) if k != "top_ancestors"])
                    first = False
                ip = item.get("path") or cloud_path_full + "/" + item.get("name", "")
                _collect_item(dict(item), ip)
            logger.info("【阶段一】iter_files_with_path 完成，共收集 %d 条目", len(cloud_items))
            fetched = True
        except Exception as e:
            if _is_405_error(e):
                logger.warning("iter_files_with_path 遭遇 405，冷却 %.0fs 后降级: %s",
                               _405_COOLDOWN_BASE, e)
                time.sleep(_405_COOLDOWN_BASE)
            else:
                logger.warning("iter_files_with_path 失败，降级: %s", e, exc_info=True)

    # ── 方案三：iterdir 手动递归（最终 fallback）─────────────────────────
    if not fetched:
        if _fn_iterdir is None:
            logger.error("iterdir 不可用，无法拉取云盘树")
            return stats, fscache_batch, strmfile_batch
        reason = "web CK 不支持 skim" if not skim_usable else "skim/iwp 均失败"
        logger.info(
            "【阶段一】iterdir 手动递归拉取云盘树: cid=%s (%s) iter_app=%s",
            cid, reason, iter_app,
        )

        _cooldown_until: float = 0.0
        _consecutive_405: int = 0

        def _wait_cooldown() -> None:
            nonlocal _cooldown_until
            now = time.time()
            if _cooldown_until > now:
                wait = _cooldown_until - now
                logger.info("全局 405 冷却中，等待 %.0fs...", wait)
                time.sleep(wait)

        def _trigger_cooldown() -> float:
            nonlocal _cooldown_until, _consecutive_405
            _consecutive_405 += 1
            cd = min(
                _405_COOLDOWN_BASE * (_405_COOLDOWN_FACTOR ** (_consecutive_405 - 1)),
                _405_COOLDOWN_MAX,
            )
            _cooldown_until = time.time() + cd
            return cd

        def _reset_cooldown() -> None:
            nonlocal _consecutive_405
            if _consecutive_405 > 0:
                _consecutive_405 = 0

        def _walk_collect(walk_cid: int, walk_path: str, depth: int = 0) -> None:
            if depth > 30:
                logger.warning("目录深度超过30层，停止递归: %s", walk_path)
                return

            # FsCache 命中时直接用缓存（跳过 API 调用）
            cache_key = str(walk_cid)
            if fscache_tree and cache_key in fscache_tree:
                cached_children = fscache_tree[cache_key]
                logger.debug("FsCache 命中(%d子项) cid=%s %s，跳过 API",
                             len(cached_children), cache_key, walk_path)
                sub_dirs = []
                for child in cached_children:
                    name = child.get("name", "")
                    if not name:
                        continue
                    ip = child.get("local_path") or f"{walk_path}/{name}"
                    if child.get("is_dir"):
                        sub_cid = int(child.get("file_id") or 0)
                        if sub_cid:
                            sub_dirs.append((sub_cid, ip))
                    else:
                        _collect_item({
                            "name":     name,
                            "pickcode": child.get("pick_code", ""),
                            "mtime":    child.get("mtime", ""),
                            "id":       child.get("file_id", ""),
                            "pid":      child.get("parent_id", ""),
                            "sha":      child.get("sha1", ""),
                            "s":        child.get("file_size", 0),
                            "t":        child.get("ctime", ""),
                        }, ip)
                for sub_cid, sub_path in sub_dirs:
                    _walk_collect(sub_cid, sub_path, depth + 1)
                return

            _wait_cooldown()
            items_raw = None
            retries_405, retries_norm = 0, 0
            while True:
                try:
                    items_raw = list(_fn_iterdir(  # type: ignore[operator]
                        client=p115_client, cid=walk_cid,
                        cooldown=api_interval, app=iter_app,
                    ))
                    _reset_cooldown()
                    break
                except Exception as e:
                    if _is_405_error(e):
                        retries_405 += 1
                        if retries_405 >= _405_MAX_RETRIES:
                            logger.error("iterdir 405 重试耗尽(%d次) %s: %s",
                                         retries_405, walk_path, e)
                            stats["errors"] += 1
                            return
                        cd = _trigger_cooldown()
                        logger.warning("iterdir 405(第%d次) %s, 冷却%.0fs: %s",
                                       retries_405, walk_path, cd, e)
                        time.sleep(cd)
                    else:
                        retries_norm += 1
                        if retries_norm >= _NORMAL_MAX_RETRIES:
                            logger.error("iterdir 失败(重试耗尽) %s: %s", walk_path, e)
                            stats["errors"] += 1
                            return
                        wait = api_interval * (2 ** (retries_norm - 1))
                        logger.warning("iterdir 失败(第%d次) %s, 等待%.1fs: %s",
                                       retries_norm, walk_path, wait, e)
                        time.sleep(wait)

            if items_raw is None:
                return
            sub_dirs = []
            for item in items_raw:
                name = item.get("name", "")
                if not name:
                    continue
                ip = f"{walk_path}/{name}"
                if item.get("is_dir"):
                    sub_cid = int(item.get("id") or item.get("file_id") or 0)
                    if sub_cid:
                        sub_dirs.append((sub_cid, ip))
                        # 目录节点单独收集进 cloud_items（用于 FsCache）
                        cloud_items.append({
                            "_item_path": ip,
                            "is_dir":  True,
                            "id":      str(sub_cid),
                            "pid":     str(walk_cid),
                            "name":    name,
                        })
                else:
                    _collect_item(dict(item), ip)
            for idx, (sub_cid, sub_path) in enumerate(sub_dirs):
                if idx > 0:
                    time.sleep(api_interval)
                _walk_collect(sub_cid, sub_path, depth + 1)

        _walk_collect(int(cid), cloud_path_full)
        logger.info("【阶段一】iterdir 手动递归完成，共收集 %d 条目", len(cloud_items))
        fetched = True

    if not cloud_items:
        logger.info("【阶段一】云盘目录树为空，无需处理")
        return stats, fscache_batch, strmfile_batch

    # ══════════════════════════════════════════════════════════════════════
    # 阶段二：本地对比 + 写文件 + 写缓存（零网盘 API 调用）
    # ══════════════════════════════════════════════════════════════════════
    logger.info("【阶段二】开始本地对比，云盘文件候选 %d 个", len(cloud_files))

    scan_count = 0
    for item in cloud_files:
        name      = item.get("name", "")
        if not name:
            continue
        pick_code = (item.get("pickcode") or item.get("pick_code")
                     or item.get("pc") or "")
        item_mtime = int(item.get("mtime") or item.get("utime") or item.get("t") or 0)
        file_id    = str(item.get("id") or item.get("file_id") or item.get("fid") or "")
        parent_id  = str(item.get("pid") or item.get("parent_id") or "")
        sha1       = item.get("sha") or item.get("sha1") or ""
        file_size  = int(item.get("s") or item.get("size") or item.get("file_size") or 0)
        ctime_val  = str(item.get("t") or item.get("ctime") or "")
        item_path  = item.get("_item_path", cloud_path_full + "/" + name)
        scan_count += 1

        # ── 过滤：mtime 时间窗口 ──────────────────────────────────────────
        if from_time > 0 and item_mtime <= from_time:
            logger.debug("#%d %s - 跳过(mtime旧 %d <= %d)",
                         scan_count, name, item_mtime, from_time)
            stats["skipped"] += 1
            continue

        # ── 过滤：非视频扩展名 ────────────────────────────────────────────
        ext = Path(name).suffix.lstrip(".").lower()
        if ext not in video_exts:
            logger.debug("#%d %s - 跳过(非视频 .%s)", scan_count, name, ext)
            stats["skipped"] += 1
            continue

        # ── 校验 pickcode ─────────────────────────────────────────────────
        if not pick_code:
            logger.error("#%d %s - 无 pickcode，跳过", scan_count, name)
            stats["errors"] += 1
            continue
        if not (len(pick_code) == 17 and pick_code.isalnum()):
            logger.error("#%d %s - pickcode 格式错误 %r，跳过", scan_count, name, pick_code)
            stats["errors"] += 1
            continue

        # ── 计算 STRM 路径和 URL（纯本地计算，不调网盘）────────────────────
        rel      = calc_rel_path(item_path, cloud_path)
        strm_url = render_strm_url(url_tmpl, link_host, pick_code, name, item_path)
        strm_name = get_strm_filename(name)
        strm_file = strm_root / rel / strm_name

        # ── 决策：本地文件是否存在 ────────────────────────────────────────
        if strm_file.exists():
            existing = strm_file.read_text(encoding="utf-8").strip()
            if existing == strm_url.strip():
                result, result_desc = "skipped", "内容相同跳过"
            elif overwrite_mode == "skip":
                result, result_desc = "skipped", "已存在(skip模式)跳过"
            else:
                # overwrite 模式：重写文件
                try:
                    strm_file.write_text(strm_url, encoding="utf-8")
                    result, result_desc = "created", "内容变更覆盖"
                except Exception as ex:
                    logger.error("#%d %s - 写入失败: %s", scan_count, name, ex)
                    stats["errors"] += 1
                    continue
        else:
            # 新建
            try:
                strm_file.parent.mkdir(parents=True, exist_ok=True)
                strm_file.write_text(strm_url, encoding="utf-8")
                result, result_desc = "created", "新建"
            except Exception as ex:
                logger.error("#%d %s - 写入失败: %s", scan_count, name, ex)
                stats["errors"] += 1
                continue

        # ── 统一日志（一条包含所有步骤）──────────────────────────────────
        logger.debug("#%d %s - %s - %s - %s",
                     scan_count, name, item_path, strm_url, result_desc)

        # ── 写 FsCache（无论 created/skipped 都写，保持目录树缓存完整）────
        if file_id:
            fscache_batch.append({
                "file_id":   file_id,
                "parent_id": parent_id,
                "name":      name,
                "local_path": item_path,
                "sha1":      sha1,
                "pick_code": pick_code,
                "file_size": file_size,
                "is_dir":    0,
                "mtime":     str(item_mtime),
                "ctime":     ctime_val,
            })

        # ── 写 StrmFile（无论 created/skipped 都写，供文件列表页显示）────
        strmfile_batch.append({
            "item_id":      pick_code,
            "strm_path":    str(strm_file),
            "strm_content": strm_url,
            "strm_mode":    "p115",
            "file_size":    file_size,
        })

        if result == "created":
            stats["created"] += 1
        else:
            stats["skipped"] += 1

    # ── 目录节点写 FsCache ────────────────────────────────────────────────
    for item in cloud_items:
        if item.get("is_dir"):
            dir_id  = str(item.get("id") or "")
            dir_pid = str(item.get("pid") or "")
            dir_name= item.get("name", "")
            dir_path= item.get("_item_path", "")
            if dir_id:
                fscache_batch.append({
                    "file_id":   dir_id,
                    "parent_id": dir_pid,
                    "name":      dir_name,
                    "local_path": dir_path,
                    "sha1":      "",
                    "pick_code": "",
                    "file_size": 0,
                    "is_dir":    1,
                    "mtime":     "",
                    "ctime":     "",
                })

    logger.info(
        "【阶段二】完成: 扫描%d个视频文件 created=%d skipped=%d errors=%d "
        "FsCache待写=%d StrmFile待写=%d",
        scan_count, stats["created"], stats["skipped"], stats["errors"],
        len(fscache_batch), len(strmfile_batch),
    )
    return stats, fscache_batch, strmfile_batch


async def resolve_cloud_cid(manager, cloud_path: str) -> str:
    """
    将云盘路径解析为 cid（目录 ID）。
    方案0（优先）：查 P115FsCache 本地缓存（遍历写入后命中率极高）
    方案A：iterdir 逐级遍历（兼容所有 CK 类型，无 405）
    方案B：fs_dir_getid（仅 web CK）
    方案C：webapi list_files_paged 逐段查（最终兜底）
    """
    cloud_path = cloud_path.strip().strip("/")
    if not cloud_path:
        return "0"

    p115_client = manager.adapter._get_p115_client()

    # ── 方案0：查 P115FsCache 本地缓存 ──────────────────────────────────────
    cached_cid = await lookup_cid_by_path("/" + cloud_path)
    if cached_cid:
        logger.debug("【resolve_cid】FsCache 命中 %r → cid=%s", cloud_path, cached_cid)
        return str(cached_cid)

    # ── 确定 iter_app ─────────────────────────────────────────────────────────
    login_app = getattr(getattr(manager.adapter, "_auth", None), "login_app", "web") or "web"
    iter_app  = "web" if login_app in _WEB_APPS_SET else login_app

    logger.debug(
        "【resolve_cid】cloud_path=%r login_app=%r iter_app=%r",
        cloud_path, login_app, iter_app,
    )

    # ── 方案A：iterdir 逐级遍历 ──────────────────────────────────────────────
    if p115_client is not None:
        try:
            from p115client.tool.iterdir import iterdir as _iterdir_fn  # type: ignore[import]

            def _resolve_by_iterdir(segments: list) -> str:
                cur_cid = 0
                for seg in segments:
                    logger.debug("【resolve_cid】iterdir 查找 %r (parent_cid=%d)", seg, cur_cid)
                    dir_items = list(_iterdir_fn(client=p115_client, cid=cur_cid, cooldown=1, app=iter_app))
                    found = next((i for i in dir_items if i.get("is_dir") and i.get("name") == seg), None)
                    if found is None:
                        raise ValueError(f"路径段未找到: {seg!r} (parent_cid={cur_cid})")
                    cur_cid = int(found.get("id") or found.get("file_id") or 0)
                    logger.debug("【resolve_cid】路径段 %r 找到 cid=%d", seg, cur_cid)
                return str(cur_cid)

            segments = [s for s in cloud_path.split("/") if s]
            cid = await asyncio.to_thread(_resolve_by_iterdir, segments)
            logger.info("【resolve_cid】iterdir 解析 %r → cid=%s", cloud_path, cid)
            return cid

        except ImportError:
            logger.warning("【resolve_cid】iterdir 不可用，尝试方案B")
        except Exception as e:
            logger.warning("【resolve_cid】iterdir 失败: %s，尝试方案B", e, exc_info=True)

    # ── 方案B：fs_dir_getid（仅 web CK）─────────────────────────────────────
    if p115_client is not None and iter_app == "web":
        try:
            def _get_dir_id(path: str) -> str:
                resp = p115_client.fs_dir_getid(path)
                if resp.get("state") and resp.get("id") is not None:
                    return str(resp["id"])
                raise ValueError(f"fs_dir_getid 异常: {resp}")

            cid = await asyncio.to_thread(_get_dir_id, "/" + cloud_path)
            logger.debug("【resolve_cid】方案B fs_dir_getid %r → cid=%s", cloud_path, cid)
            return cid
        except Exception as e:
            logger.debug("【resolve_cid】方案B 失败，走方案C: %s", e)

    # ── 方案C：webapi list_files_paged 逐段（最终兜底）──────────────────────
    logger.debug("【resolve_cid】方案C: webapi 逐段解析 %r", cloud_path)
    segments = [s for s in cloud_path.split("/") if s]
    cid = "0"
    current_path = ""
    for seg in segments:
        current_path = f"{current_path}/{seg}"
        try:
            entries, _ = await manager.adapter.list_files_paged(current_path, cid=cid, limit=200)
            found = next((e for e in entries if e.is_dir and e.name == seg), None)
            if found:
                cid = found.file_id
            else:
                logger.warning("【resolve_cid】路径段未找到: %s (parent_cid=%s)", seg, cid)
                return ""
        except Exception as e:
            logger.error("【resolve_cid】解析路径失败 %s: %s", current_path, e)
            return ""
    return cid

