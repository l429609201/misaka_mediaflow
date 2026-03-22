# src/services/font_index_service.py
# 字体索引持久化服务 — 参考 fontInAss fontManager.py 设计
#
# 核心能力:
#   1. scan_and_sync()          - 扫描字体目录, 与 DB 做 diff, 增/删/改
#   2. find_font_in_db()        - 按字体名+粗斜体从 DB 查找 (path,face_index)
#   3. register_subtitle()      - 登记外部字幕文件, 解析字体 key 列表
#   4. get_subtitle_font_keys() - 快速读取字幕已缓存的字体 key 列表
#   5. sync_subtitles()         - 扫描字幕目录, 登记/清理字幕记录

import asyncio, hashlib, json, logging, os, time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_FONTS_ROOT     = Path(os.environ.get('BUILTIN_FONT_DIR', '/app/config/fonts'))
_FONTS_DOWNLOAD = _FONTS_ROOT / 'downloads'
_FONT_EXTS      = {'.ttf', '.otf', '.ttc', '.otc'}
_SUB_EXTS       = {'.ass', '.ssa', '.srt'}
_lookup_cache: dict = {}
_LOOKUP_CACHE_TTL = 300
_last_sync_at: float = 0.0
_SYNC_MIN_INTERVAL = 60
_scan_lock: asyncio.Lock = asyncio.Lock()   # 防止并发扫描导致重复 INSERT


# ═══ Part 1: 工具函数 ═══════════════════════════════════════════════════════════

def _md5_of_path(path: str) -> str:
    """路径字符串的 MD5，用作数据库唯一键"""
    return hashlib.md5(path.encode("utf-8")).hexdigest()


def _md5_of_file(path: str) -> str:
    """文件内容 MD5（只读前 256KB，速度与准确性平衡）"""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            h.update(f.read(256 * 1024))
    except OSError:
        pass
    return h.hexdigest()


def _read_font_faces(path: str) -> list:
    """
    读取字体文件所有 face 元数据，返回列表。
    每项: {"face_index", "family_names", "full_names",
           "postscript_names", "weight", "is_bold", "is_italic"}
    读 nameID 1/4/6 及 OS/2 字重标志，与 fontInAss get_font_info 对齐。
    """
    try:
        from fontTools.ttLib import TTFont, TTCollection
    except ImportError:
        logger.warning("[font_idx] fonttools 未安装，无法读取字体元数据")
        return []

    results = []
    ext = Path(path).suffix.lower()

    def _extract(font, idx: int) -> Optional[dict]:
        family, full, ps = set(), set(), set()
        weight = 400
        bold = italic = False
        try:
            for rec in font["name"].names:
                if rec.nameID not in (1, 4, 6):
                    continue
                try:
                    val = rec.toUnicode().strip()
                except Exception:
                    continue
                # 移除 NULL byte：老式中文字体（汉鼎、文鼎等）name 表常含 UTF-16BE 残留的
                # \x00 或 C 风格末尾填充，PostgreSQL VARCHAR 列不接受 NULL byte（\x00）
                val = val.replace('\x00', '').strip()
                if not val:
                    continue
                if rec.nameID == 1:
                    family.add(val)
                elif rec.nameID == 4:
                    full.add(val)
                elif rec.nameID == 6:
                    ps.add(val)
            if "OS/2" in font:
                os2 = font["OS/2"]
                weight = getattr(os2, "usWeightClass", 400) or 400
                fs_sel = getattr(os2, "fsSelection", 0) or 0
                bold   = bool(fs_sel & 0x20)
                italic = bool(fs_sel & 0x01)
            if not family and not full and not ps:
                return None
        except Exception as e:
            logger.debug("[font_idx] 读取字体元数据失败 %s#%d: %s", path, idx, e)
            return None
        return {
            "face_index": idx,
            "family_names": sorted(family),
            "full_names": sorted(full),
            "postscript_names": sorted(ps),
            "weight": weight,
            "is_bold": 1 if bold else 0,
            "is_italic": 1 if italic else 0,
        }

    try:
        if ext in (".ttc", ".otc"):
            col = TTCollection(path)
            for i in range(len(col.fonts)):
                font = TTFont(path, fontNumber=i, lazy=True)
                rec = _extract(font, i)
                if rec:
                    results.append(rec)
                font.close()
        else:
            font = TTFont(path, lazy=True)
            rec = _extract(font, 0)
            if rec:
                results.append(rec)
            font.close()
    except Exception as e:
        logger.debug("[font_idx] 跳过字体文件 %s: %s", path, e)

    return results


# ═══ Part 2: DB 基础操作 ════════════════════════════════════════════════════════

def _collect_disk_fonts(root: Path) -> dict:
    """递归扫描字体目录，返回 {绝对路径str: file_size}"""
    result = {}
    if not root.exists():
        return result
    for p in root.rglob("*"):
        if p.suffix.lower() not in _FONT_EXTS:
            continue
        try:
            result[str(p)] = p.stat().st_size
        except OSError:
            pass
    return result


async def _db_get_all_font_files(db) -> dict:
    """查询所有 FontFile，返回 {path_hash: {id, path, file_hash, file_size}}"""
    from sqlalchemy import select
    from src.db.models import FontFile
    rows = (await db.execute(select(FontFile))).scalars().all()
    return {
        r.path_hash: {
            "id": r.id,
            "path": r.path,
            "file_hash": r.file_hash,
            "file_size": r.file_size,
        }
        for r in rows
    }


async def _db_upsert_font_file(db, path: str, file_size: int, file_hash: str) -> int:
    """
     Upsert FontFile，返回行 id。
     已存在(path_hash 相同)则更新 file_size/file_hash/scanned_at，否则新建。
     """
    from sqlalchemy import select
    from src.db.models import FontFile
    from src.core.timezone import tm
    ph = _md5_of_path(path)
    row = (await db.execute(select(FontFile).where(FontFile.path_hash == ph))).scalars().first()
    if row:
        row.file_size  = file_size
        row.file_hash  = file_hash
        row.scanned_at = tm.now()
    else:
        row = FontFile(path=path, path_hash=ph,
                        file_size=file_size, file_hash=file_hash,
                        scanned_at=tm.now())
        db.add(row)
    await db.flush()   # 让 row.id 可用，但不 commit（由调用方控制）
    return row.id


async def _db_delete_font_files(db, path_hashes: list):
    """批量删除 FontFile（ON DELETE CASCADE 自动级联删 FontFace + FontName）"""
    if not path_hashes:
        return
    from sqlalchemy import select, delete
    from src.db.models import FontFile
    # 分批删除，避免 IN 子句过长
    for i in range(0, len(path_hashes), 200):
        batch = path_hashes[i: i + 200]
        await db.execute(
            delete(FontFile).where(FontFile.path_hash.in_(batch))
        )


async def _db_insert_font_faces(db, file_id: int, faces: list):
    """批量插入 FontFace + FontName，所有名字展开为独立索引行（小写）"""
    from src.db.models import FontFace, FontName
    from src.core.timezone import tm
    now = tm.now()
    for face in faces:
        ff = FontFace(
            file_id          = file_id,
            face_index       = face["face_index"],
            family_names     = json.dumps(face["family_names"],     ensure_ascii=False),
            full_names       = json.dumps(face["full_names"],        ensure_ascii=False),
            postscript_names = json.dumps(face["postscript_names"], ensure_ascii=False),
            weight           = face["weight"],
            is_bold          = face["is_bold"],
            is_italic        = face["is_italic"],
            scanned_at       = now,
        )
        db.add(ff)
        await db.flush()   # 获取 ff.id

        all_names: set = set()
        for lst in (face["family_names"], face["full_names"], face["postscript_names"]):
            for n in lst:
                if n:
                    # 再次清洗 NULL byte（防御：_extract 已清洗，此处为双重保险）
                    clean = n.replace('\x00', '').strip().lower()
                    if clean:
                        all_names.add(clean)
        for name in all_names:
            db.add(FontName(name=name, face_id=ff.id))


async def _process_insert(path: str) -> int:
    """
     读取单个字体文件元数据并入库，返回成功写入的 face 数量。
     每个文件独立 session + commit，单文件失败不污染整批事务。
     """
    try:
        fsize = os.path.getsize(path)
        fhash = await asyncio.to_thread(_md5_of_file, path)
        faces = await asyncio.to_thread(_read_font_faces, path)
        if not faces:
            logger.debug("[font_idx] 跳过（无有效 face）: %s", path)
            return 0
        from src.db import get_async_session_local
        async with get_async_session_local() as db:
            file_id = await _db_upsert_font_file(db, path, fsize, fhash)
            await _db_insert_font_faces(db, file_id, faces)
            await db.commit()
        return len(faces)
    except Exception as e:
        # 已知可忽略的异常，降为 DEBUG 级别（不产生 WARNING 日志噪音）：
        #   - UniqueViolation      : 并发扫描竞争写入同一文件（正常并发冲突）
        #   - CharacterNotInRepertoire / invalid byte sequence
        #                          : 老式字体 name 表含 \x00，PostgreSQL 拒绝写入
        err_str = str(e)
        if (
            "UniqueViolation" in err_str
            or "unique constraint" in err_str.lower()
            or "duplicate key" in err_str.lower()
            or "Duplicate entry" in err_str                    # MySQL
            or "CharacterNotInRepertoire" in err_str           # asyncpg \x00 in VARCHAR
            or "invalid byte sequence" in err_str.lower()      # PostgreSQL generic encoding
        ):
            logger.debug("[font_idx] 字体跳过（已存在或名称含非法字节）: %s", path)
            return 0
        logger.warning("[font_idx] 入库失败 %s: %s", path, e)
        return 0


# ═══ Part 3: 扫描同步 & 字体查找 ════════════════════════════════════════════════

async def scan_and_sync(force: bool = False) -> dict:
    """
    扫描字体目录并与 DB 做 diff 同步（对齐 fontInAss sync_db_with_dir）。

    返回统计: {"inserted": N, "deleted": N, "unchanged": N, "elapsed": float}
    force=True 时忽略 _SYNC_MIN_INTERVAL 限制立即执行。

    变更检测：
      - 磁盘有、DB 无             → INSERT
      - 磁盘无、DB 有             → DELETE (级联清 face + name)
      - 两者都有但 file_size 不同 → DELETE 旧 + INSERT 新

    并发保护：
      - _scan_lock 保证同一时刻只有一次扫描在运行
      - 若已有扫描正在进行，新触发请求立即返回（不排队等待）
    """
    global _last_sync_at, _lookup_cache

    now = time.monotonic()
    if not force and (now - _last_sync_at) < _SYNC_MIN_INTERVAL:
        logger.debug("[font_idx] 距上次同步不足 %ds，跳过", _SYNC_MIN_INTERVAL)
        return {}

    # 如果已有扫描在进行，不排队等待（直接跳过，避免并发重复写入）
    if _scan_lock.locked():
        logger.info("[font_idx] 上一次扫描仍在进行中，跳过本次触发")
        return {}

    async with _scan_lock:
        # 拿到锁后再做一次 interval 检查（防止两个 force=True 几乎同时触发的情况）
        now = time.monotonic()
        if not force and (now - _last_sync_at) < _SYNC_MIN_INTERVAL:
            return {}

        t0 = time.monotonic()
        logger.info("[font_idx] 开始字体目录扫描同步: %s", _FONTS_ROOT)

        disk_fonts = await asyncio.to_thread(_collect_disk_fonts, _FONTS_ROOT)

        from src.db import get_async_session_local
        # ── 第一步：读取 DB 快照 + 执行删除（单独 session，确保 commit）────────
        async with get_async_session_local() as db:
            db_fonts = await _db_get_all_font_files(db)

            disk_hash_map = {_md5_of_path(p): p for p in disk_fonts}
            disk_set = set(disk_hash_map.keys())
            db_set   = set(db_fonts.keys())

            to_delete        = list(db_set - disk_set)
            to_insert_hashes = disk_set - db_set
            # 文件大小变化视为内容变化：先删后插
            to_update = {
                ph for ph in disk_set & db_set
                if disk_fonts[disk_hash_map[ph]] != db_fonts[ph]["file_size"]
            }
            to_delete        += list(to_update)
            to_insert_hashes |= to_update

            if to_delete:
                await _db_delete_font_files(db, to_delete)
                await db.commit()
                logger.info("[font_idx] 删除字体记录: %d 条（文件已移除或内容变化）", len(to_delete))

        # ── 第二步：逐文件独立 session 插入，单文件失败不影响其他文件────────────
        to_insert_paths = [disk_hash_map[ph] for ph in to_insert_hashes]
        inserted_faces = 0
        for path in to_insert_paths:
            inserted_faces += await _process_insert(path)

        _lookup_cache.clear()
        _last_sync_at = time.monotonic()

        stat = {
            "inserted":  len(to_insert_paths),
            "deleted":   len(to_delete),
            "unchanged": len(disk_set & db_set) - len(to_update),
            "elapsed":   round(time.monotonic() - t0, 2),
        }
        logger.info(
            "[font_idx] 同步完成: 新增=%d 删除=%d 未变=%d 耗时=%.2fs",
            stat["inserted"], stat["deleted"], stat["unchanged"], stat["elapsed"],
        )
        return stat


async def find_font_in_db(
    name: str,
    is_bold: bool = False,
    is_italic: bool = False,
) -> Optional[tuple]:
    """
    从 DB 按字体名查找最匹配的 (path, face_index)。

    匹配策略（对齐 fontInAss select_font_local）：
      层0: 精确匹配 name + bold + italic
      层1: 放宽 bold/italic，按字重接近度取最佳 face
      层2: 返回 None（交由调用方处理在线下载或内存扫描降级）

    带 5 分钟内存缓存，避免同一次字幕处理反复查 DB。
    """
    name_lower = name.strip().lower().lstrip("@")
    cache_key = (name_lower, is_bold, is_italic)
    now = time.monotonic()

    if cache_key in _lookup_cache:
        val, expire = _lookup_cache[cache_key]
        if now < expire:
            return val
        del _lookup_cache[cache_key]

    result = None
    try:
        from src.db import get_async_session_local
        from sqlalchemy import select
        from src.db.models import FontName, FontFace, FontFile
        async with get_async_session_local() as db:
            stmt = (
                select(FontFile.path, FontFace.face_index,
                        FontFace.weight, FontFace.is_bold, FontFace.is_italic)
                .join(FontFace, FontFace.file_id == FontFile.id)
                .join(FontName, FontName.face_id == FontFace.id)
                .where(FontName.name == name_lower)
            )
            candidates = (await db.execute(stmt)).fetchall()

        if candidates:
            # 层0: 精确匹配
            for row in candidates:
                if bool(row.is_bold) == is_bold and bool(row.is_italic) == is_italic:
                    result = (row.path, row.face_index)
                    break
            # 层1: 按字重接近度取最佳
            if result is None:
                target_w = 700 if is_bold else 400
                best = min(candidates, key=lambda r: abs((r.weight or 400) - target_w))
                result = (best.path, best.face_index)
    except Exception as e:
        logger.debug("[font_idx] DB 查找字体失败: %s -> %s", name, e)

    _lookup_cache[cache_key] = (result, now + _LOOKUP_CACHE_TTL)
    return result


# ═══ Part 4: 外部字幕文件登记 & 同步 ═══════════════════════════════════════════

def _parse_subtitle_font_keys(path: str) -> list:
    """
    解析字幕文件（ASS/SRT），返回用到的字体 key 列表。
    key 格式: "字体名^Regular" / "字体名^Bold" 等，与 subtitle_builtin.analyse_ass 对齐。
    非 ASS/SRT 文件返回空列表。
    """
    try:
        from src.services.subtitle_builtin import analyse_ass, srt_to_ass, _detect_format
        raw = Path(path).read_bytes()
        fmt = _detect_format(raw)
        if fmt == "ass":
            text_content = raw.decode("utf-8-sig", errors="replace")
        elif fmt == "srt":
            text_content = srt_to_ass(raw.decode("utf-8-sig", errors="replace"))
        else:
            return []
        font_chars = analyse_ass(text_content)
        return list(font_chars.keys())
    except Exception as e:
        logger.debug("[font_idx] 解析字幕字体失败 %s: %s", path, e)
        return []


async def register_subtitle(file_path: str, item_id: str = "") -> bool:
    """
    登记/更新单个外部字幕文件到 subtitle_file 表（幂等）。
    file_hash 未变化则跳过。
    返回 True=已写入/更新，False=跳过或失败。
    """
    try:
        from src.db import get_async_session_local
        from sqlalchemy import select
        from src.db.models import SubtitleFile
        from src.core.timezone import tm

        ph    = _md5_of_path(file_path)
        fsize = os.path.getsize(file_path)
        fhash = await asyncio.to_thread(_md5_of_file, file_path)
        now   = tm.now()

        async with get_async_session_local() as db:
            existing = (
                await db.execute(select(SubtitleFile).where(SubtitleFile.path_hash == ph))
            ).scalars().first()

            if existing and existing.file_hash == fhash:
                logger.debug("[font_idx] 字幕未变化，跳过: %s", file_path)
                return False

            font_keys      = await asyncio.to_thread(_parse_subtitle_font_keys, file_path)
            font_keys_json = json.dumps(font_keys, ensure_ascii=False)

            if existing:
                existing.file_hash  = fhash
                existing.file_size  = fsize
                existing.font_keys  = font_keys_json
                existing.item_id    = item_id or ""
                existing.scanned_at = now
            else:
                db.add(SubtitleFile(
                    item_id    = item_id or "",
                    file_path  = file_path,
                    path_hash  = ph,
                    file_hash  = fhash,
                    file_size  = fsize,
                    font_keys  = font_keys_json,
                    scanned_at = now,
                ))
            await db.commit()

        logger.info("[font_idx] 字幕已登记: %s font_keys=%d 个", file_path, len(font_keys))
        return True
    except Exception as e:
        logger.warning("[font_idx] 字幕登记失败 %s: %s", file_path, e)
        return False


async def get_subtitle_font_keys(file_path: str) -> list:
    """
    快速获取字幕文件对应的字体 key 列表（优先从 DB 缓存读取）。
    DB 未命中或文件内容变化时实时解析并写入。
    """
    try:
        from src.db import get_async_session_local
        from sqlalchemy import select
        from src.db.models import SubtitleFile
        ph = _md5_of_path(file_path)
        async with get_async_session_local() as db:
            rec = (
                await db.execute(select(SubtitleFile).where(SubtitleFile.path_hash == ph))
            ).scalars().first()
            if rec:
                cur_hash = await asyncio.to_thread(_md5_of_file, file_path)
                if cur_hash == rec.file_hash:
                    return json.loads(rec.font_keys or "[]")
    except Exception as e:
        logger.debug("[font_idx] 读取字幕字体缓存失败: %s", e)

    await register_subtitle(file_path)
    return await asyncio.to_thread(_parse_subtitle_font_keys, file_path)


async def sync_subtitles(subtitle_root: Path) -> dict:
    """
    扫描字幕目录，登记新字幕文件 / 清理已删除字幕记录。
    返回统计: {"inserted": N, "deleted": N, "unchanged": N}
    """
    if not subtitle_root.exists():
        return {"inserted": 0, "deleted": 0, "unchanged": 0}

    t0 = time.monotonic()

    disk_subs: dict = {}
    for p in subtitle_root.rglob("*"):
        if p.suffix.lower() in _SUB_EXTS:
            try:
                disk_subs[str(p)] = _md5_of_path(str(p))
            except OSError:
                pass

    from src.db import get_async_session_local
    from sqlalchemy import select, delete
    from src.db.models import SubtitleFile
    async with get_async_session_local() as db:
        all_recs = (await db.execute(select(SubtitleFile))).scalars().all()
        db_subs = {r.path_hash: r.file_path for r in all_recs}

    disk_ph_set = set(disk_subs.values())
    db_ph_set   = set(db_subs.keys())

    # 删除磁盘上已不存在的字幕记录
    to_delete_ph = list(db_ph_set - disk_ph_set)
    deleted = 0
    if to_delete_ph:
        async with get_async_session_local() as db:
            for i in range(0, len(to_delete_ph), 200):
                batch = to_delete_ph[i: i + 200]
                await db.execute(
                    delete(SubtitleFile).where(SubtitleFile.path_hash.in_(batch))
                )
            await db.commit()
        deleted = len(to_delete_ph)
        logger.info("[font_idx] 清理已删字幕记录: %d 条", deleted)

    # 登记新字幕文件
    inserted = unchanged = 0
    for fp, ph in disk_subs.items():
        if ph not in db_ph_set:
            ok = await register_subtitle(fp)
            inserted += (1 if ok else 0)
        else:
            unchanged += 1

    logger.info(
        "[font_idx] 字幕同步完成: 新增=%d 删除=%d 未变=%d 耗时=%.2fs",
        inserted, deleted, unchanged, round(time.monotonic() - t0, 2),
    )
    return {"inserted": inserted, "deleted": deleted, "unchanged": unchanged}
