# src/services/p115/modules/traversal.py
# 遍历模块
# 负责 115 网盘目录树遍历和 STRM 文件生成的核心逻辑。
# 所有函数为普通同步函数（在 asyncio.to_thread 中执行），或 async 函数（调用 DB）。
#
#   - 优先使用 iter_files_with_path_skim（单次流式遍历整棵树）
#   - fallback 到 iterdir 手动递归
#   - 边遍历边写 STRM，收集 fscache_batch / strmfile_batch

import asyncio
import logging
import time
from pathlib import Path

from src.services.p115.modules.strm_writer import (
    calc_rel_path, get_strm_filename, render_strm_url, write_strm,
)
from src.services.p115.modules.db_ops import lookup_cid_by_path

logger = logging.getLogger(__name__)

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
) -> tuple[dict, list[dict], list[dict]]:
    """
    遍历 115 目录树，对每个视频文件写 .strm。
    返回 (stats, fscache_batch, strmfile_batch)：
      stats         — {"created": N, "skipped": N, "errors": N}
      fscache_batch — 目录节点+文件节点，供调用方用 ORM 写入 P115FsCache
      strmfile_batch — 新建的 STRM 记录，供调用方用 ORM 写入 StrmFile

    优先使用 iter_files_with_path_skim（skim 可用且非 web CK）；
    fallback 到 iterdir 手动递归。
    """
    stats: dict = {"created": 0, "skipped": 0, "errors": 0}
    fscache_batch: list[dict] = []
    strmfile_batch: list[dict] = []

    p115_client = manager.adapter._get_p115_client()
    if p115_client is None:
        logger.error("【遍历】p115_client 不可用，无法同步")
        return stats, fscache_batch, strmfile_batch

    cloud_path_full = "/" + cloud_path.strip("/")
    scan_count = 0

    logger.debug(
        "【遍历】入参: cid=%r cloud_path=%r strm_root=%r "
        "from_time=%d overwrite_mode=%r api_interval=%.1f video_exts=%s",
        cid, cloud_path, str(strm_root), from_time, overwrite_mode, api_interval, video_exts,
    )

    # ── 读取 login_app，决定 skim 参数 ──────────────────────────────────────
    login_app_raw = getattr(getattr(manager.adapter, "_auth", None), "login_app", "") or ""
    iter_app_for_skim = "web" if login_app_raw in _WEB_APPS_SET else login_app_raw
    # skim 可用条件：库支持 AND 非 web CK（web CK 走 /os_windows 接口会 errno=99）
    skim_usable = has_skim and (login_app_raw not in _WEB_APPS_SET)

    logger.debug(
        "【遍历】Cookie 类型: login_app=%r iter_app=%r skim_usable=%s",
        login_app_raw, iter_app_for_skim, skim_usable,
    )

    # ── 尝试导入 p115client 遍历工具 ─────────────────────────────────────────
    try:
        from p115client.tool.iterdir import iter_files_with_path_skim, iterdir
        has_skim = True
    except ImportError:
        try:
            from p115client.tool.iterdir import iterdir
            has_skim = False
            logger.debug("【遍历】iter_files_with_path_skim 不可用，降级到 iterdir 递归")
        except ImportError:
            logger.error("【遍历】p115client.tool.iterdir 不可用")
            return stats, fscache_batch, strmfile_batch

    # ── 内部函数：处理单个文件条目 ────────────────────────────────────────────
    def _process_file(item: dict, item_path: str) -> None:
        nonlocal scan_count
        scan_count += 1

        name      = item.get("name", "")
        pick_code = item.get("pickcode") or item.get("pick_code") or item.get("pc", "")
        item_mtime= int(item.get("mtime") or item.get("utime") or item.get("t") or 0)
        file_id   = str(item.get("id") or item.get("file_id") or item.get("fid") or "")
        parent_id = str(item.get("pid") or item.get("parent_id") or "")
        sha1      = item.get("sha") or item.get("sha1") or ""
        file_size = int(item.get("s") or item.get("size") or item.get("file_size") or 0)
        ctime     = str(item.get("t") or item.get("ctime") or "")

        logger.debug(
            "【遍历】处理条目 #%d: name=%r path=%r pickcode=%r mtime=%d",
            scan_count, name, item_path, pick_code, item_mtime,
        )

        if from_time > 0 and item_mtime <= from_time:
            logger.debug("【遍历】跳过(mtime旧): %r mtime=%d <= from_time=%d", name, item_mtime, from_time)
            stats["skipped"] += 1
            return

        ext = Path(name).suffix.lstrip(".").lower()
        if ext not in video_exts:
            logger.debug("【遍历】跳过(非视频): %r ext=%r", name, ext)
            stats["skipped"] += 1
            return

        if not pick_code:
            logger.error("【遍历】%s 不存在 pickcode，跳过: keys=%s", name, list(item.keys()))
            stats["errors"] += 1
            return

        if not (len(pick_code) == 17 and pick_code.isalnum()):
            logger.error("【遍历】pickcode 格式错误 %r，跳过: %s", pick_code, name)
            stats["errors"] += 1
            return

        rel      = calc_rel_path(item_path, cloud_path)
        strm_url = render_strm_url(url_tmpl, link_host, pick_code, name, item_path)

        logger.debug("【遍历】准备写STRM: name=%r rel=%r url=%r", name, str(rel), strm_url)
        result = write_strm(strm_root, rel, name, strm_url, overwrite_mode)

        # 无论 created/skipped 都写 FsCache（保持目录树最新）
        if file_id:
            fscache_batch.append({
                "file_id":    file_id,
                "parent_id":  parent_id,
                "name":       name,
                "local_path": item_path,
                "sha1":       sha1,
                "pick_code":  pick_code,
                "file_size":  file_size,
                "is_dir":     0,
                "mtime":      str(item_mtime),
                "ctime":      ctime,
            })

        if result == "created":
            stats["created"] += 1
            # 只有实际写出文件才记录 StrmFile
            strm_name = get_strm_filename(name)
            strmfile_batch.append({
                "item_id":      pick_code,
                "strm_path":    str(strm_root / rel / strm_name),
                "strm_content": strm_url,
                "strm_mode":    "p115",
                "file_size":    file_size,
            })
        elif result == "skipped":
            stats["skipped"] += 1
        else:
            stats["errors"] += 1

    # ══ 方案一：iter_files_with_path_skim（非 web CK 可用）════════════════════
    if has_skim and skim_usable:
        logger.info(
            "【遍历】使用 iter_files_with_path_skim: cid=%s cloud_path=%r app=%s overwrite=%s",
            cid, cloud_path, iter_app_for_skim, overwrite_mode,
        )
        try:
            iter_kwargs: dict = {
                "cid": int(cid),
                "app": iter_app_for_skim,
            }
            if iter_app_for_skim not in _WEB_APPS_SET:
                iter_kwargs["headers"] = {"user-agent": _IOS_UA}

            _first_logged = False
            for item in iter_files_with_path_skim(p115_client, **iter_kwargs):
                if not _first_logged:
                    logger.debug("【遍历】skim 第一个 item 字段: %s", dict(item))
                    _first_logged = True
                item_path = item.get("path") or cloud_path_full + "/" + item.get("name", "")
                _process_file(dict(item), item_path)

            logger.info("【遍历】iter_files_with_path_skim 完成，扫描 %d 个条目，stats=%s",
                        scan_count, stats)
            return stats, fscache_batch, strmfile_batch

        except Exception as e:
            logger.warning("【遍历】iter_files_with_path_skim 失败，回退到 iterdir 递归: %s",
                           e, exc_info=True)

    # ── 方案二：iterdir 手动递归 —— 确定 iter_app ────────────────────────────
    # login_app 与 iter_app 必须对齐：web CK 用 "web"，iOS/Android CK 用对应值
    login_app_raw2 = getattr(getattr(manager.adapter, "_auth", None), "login_app", "") or ""
    iter_app = "web" if login_app_raw2 in _WEB_APPS_SET else login_app_raw2
    reason = "web CK 不支持 skim" if not skim_usable else "skim 失败，降级"
    logger.info(
        "【遍历】使用 iterdir 递归: cid=%s cloud_path=%r (%s) iter_app=%s",
        cid, cloud_path, reason, iter_app,
    )

    def _walk(walk_cid: int, walk_path: str, depth: int = 0) -> None:
        if depth > 30:
            logger.warning("【遍历】目录深度超过30层，停止递归: %s", walk_path)
            return

        items = None
        for attempt in range(3):
            try:
                items = list(iterdir(
                    client=p115_client,
                    cid=walk_cid,
                    cooldown=api_interval,
                    app=iter_app,
                ))
                break
            except Exception as e:
                err_str = str(e)
                wait = api_interval * (2 ** attempt)
                if attempt < 2:
                    logger.warning("【遍历】iterdir 失败(第%d次) path=%s: %s, 等待%.1fs",
                                   attempt + 1, walk_path, err_str, wait)
                    time.sleep(wait)
                else:
                    logger.error("【遍历】iterdir 失败(重试耗尽) path=%s: %s", walk_path, err_str)
                    stats["errors"] += 1
                    return

        if items is None:
            return

        sub_dirs = []
        for item in items:
            name = item.get("name", "")
            if not name:
                continue
            item_path = f"{walk_path}/{name}"
            if item.get("is_dir"):
                sub_cid = int(item.get("id") or item.get("file_id") or 0)
                if sub_cid:
                    sub_dirs.append((sub_cid, item_path))
                    logger.debug("【遍历】发现子目录: %r cid=%d", item_path, sub_cid)
                    # 收集目录节点到 FsCache
                    fscache_batch.append({
                        "file_id":    str(sub_cid),
                        "parent_id":  str(walk_cid),
                        "name":       name,
                        "local_path": item_path,
                        "sha1":       "",
                        "pick_code":  "",
                        "file_size":  0,
                        "is_dir":     1,
                        "mtime":      "",
                        "ctime":      "",
                    })
            else:
                _process_file(item, item_path)

        for idx, (sub_cid, sub_path) in enumerate(sub_dirs):
            if idx > 0:
                time.sleep(api_interval)
            _walk(sub_cid, sub_path, depth + 1)

    _walk(int(cid), cloud_path_full)
    logger.info("【遍历】iterdir 递归完成，扫描 %d 个条目，stats=%s", scan_count, stats)
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
            from p115client.tool.iterdir import iterdir

            def _resolve_by_iterdir(segments: list) -> str:
                cur_cid = 0
                for seg in segments:
                    logger.debug("【resolve_cid】iterdir 查找 %r (parent_cid=%d)", seg, cur_cid)
                    dir_items = list(iterdir(client=p115_client, cid=cur_cid, cooldown=1, app=iter_app))
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

