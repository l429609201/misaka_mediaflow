# src/services/subtitle_builtin.py
# 内置字幕字体子集化引擎（无需外部 fontInAss 服务）
#
# 工作流程（等同 fontInAss nginx 模式）：
#   1. 解析 ASS 字幕，提取每个字体实际用到的字符集
#   2. 本地字体库扫描（挂载目录 /data/config/fonts，排除 downloads 子目录）
#   3. 本地找不到时从 fontInAss 在线字体库下载，保存至 /data/config/fonts/downloads
#   4. fonttools 对每个字体做子集化（只保留用到的字形，大幅减小体积）
#   5. UUEncode 编码，写入 ASS [Fonts] 段，返回处理后的字幕字节
#
# 缓存策略：
#   - 按 md5(ass_bytes) 缓存处理结果（不同 item 相同字幕内容也能命中）
#   - 已读取的字体文件 bytes 缓存在内存（最多 60 条，FIFO 淘汰）
#   - 在线字体下载后持久化到 downloads 目录，下次直接读文件
# ═══════════════════════════════════════════════════════════
# Part 2: 本地字体库扫描（排除 downloads 子目录）
# ═══════════════════════════════════════════════════════════

_FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}


def _read_font_names_from_file(path: Path) -> list[tuple[str, int]]:
    """
    用 fonttools 读取字体文件里的所有字体名（支持 TTC 集合）。
    返回 [(小写字体名, face_index), ...]
    """
    try:
        from fontTools.ttLib import TTFont, TTCollection
    except ImportError:
        logger.warning("[builtin] fonttools 未安装，无法扫描本地字体")
        return []

    results = []
    ext = path.suffix.lower()
    try:
        if ext in (".ttc", ".otc"):
            col = TTCollection(str(path))
            for idx in range(len(col.fonts)):
                font = TTFont(str(path), fontNumber=idx, lazy=True)
                for rec in font["name"].names:
                    if rec.nameID in (1, 4):  # Family / Full name
                        try:
                            name = rec.toUnicode().strip().lower()
                        except Exception:
                            continue
                        if name:
                            results.append((name, idx))
                font.close()
        else:
            font = TTFont(str(path), lazy=True)
            for rec in font["name"].names:
                if rec.nameID in (1, 4):
                    try:
                        name = rec.toUnicode().strip().lower()
                    except Exception:
                        continue
                    if name:
                        results.append((name, 0))
            font.close()
    except Exception as e:
        logger.debug("[builtin] 跳过字体文件 %s: %s", path.name, e)
    return results


def _scan_local_fonts() -> dict[str, tuple[str, int]]:
    """
    扫描 _FONTS_ROOT 目录下的所有字体文件（**递归**），
    但排除 downloads 子目录（downloads 目录通过 find_font 时单独兜底查找）。
    返回 {小写字体名: (文件绝对路径, face_index)}
    """
    result: dict[str, tuple[str, int]] = {}
    if not _FONTS_ROOT.exists():
        return result

    for path in _FONTS_ROOT.rglob("*"):
        # 排除 downloads 子目录
        if _FONTS_DOWNLOAD in path.parents or path == _FONTS_DOWNLOAD:
            continue
        if path.suffix.lower() not in _FONT_EXTS:
            continue
        for name, idx in _read_font_names_from_file(path):
            if name not in result:          # 先来先得，不覆盖
                result[name] = (str(path), idx)

    logger.info("[builtin] 本地字体扫描完成: %d 条（排除 downloads）", len(result))
    return result


def _get_local_map() -> dict[str, tuple[str, int]]:
    global _local_map, _local_map_at
    now = time.monotonic()
    if _local_map and (now - _local_map_at) < _LOCAL_MAP_TTL:
        return _local_map
    _local_map = _scan_local_fonts()
    _local_map_at = now
    return _local_map


def _find_in_map(name_lower: str, fm: dict) -> Optional[tuple[str, int]]:
    """在字体映射中查找：精确 → 去 @ → 前缀模糊"""
    if name_lower in fm:
        return fm[name_lower]
    key2 = name_lower.lstrip("@")
    if key2 in fm:
        return fm[key2]
    for k, v in fm.items():
        if k.startswith(key2) or key2.startswith(k):
            return v
    return None


def find_local_font(font_name: str) -> Optional[tuple[str, int]]:
    """
    查找本地字体（不含 downloads 目录）。
    返回 (绝对路径, face_index) 或 None。
    """
    return _find_in_map(font_name.lower().strip(), _get_local_map())


def find_downloaded_font(font_name: str) -> Optional[tuple[str, int]]:
    """
    在 downloads 目录中查找已下载的字体（单独扫描，不缓存）。
    """
    if not _FONTS_DOWNLOAD.exists():
        return None
    dm: dict[str, tuple[str, int]] = {}
    for path in _FONTS_DOWNLOAD.iterdir():
        if path.suffix.lower() not in _FONT_EXTS:
            continue
        for name, idx in _read_font_names_from_file(path):
            if name not in dm:
                dm[name] = (str(path), idx)
    return _find_in_map(font_name.lower().strip(), dm)


# ═══════════════════════════════════════════════════════════
# Part 3: 在线字体库（fontInAss onlineFonts.json）
# ═══════════════════════════════════════════════════════════

async def _load_online_index() -> dict[str, dict]:
    """
    加载 fontInAss 在线字体库索引。
    优先读本地缓存文件（24h 内有效），过期后重新拉取。
    索引格式: {小写字体名: {"name": str, "url": str}}
    """
    global _online_index, _online_index_at
    now = time.monotonic()
    if _online_index and (now - _online_index_at) < _ONLINE_DB_TTL:
        return _online_index

    import json as _json

    # 先尝试读本地缓存
    if _ONLINE_DB_PATH.exists():
        try:
            raw = _json.loads(_ONLINE_DB_PATH.read_bytes())
            _online_index = {e["name"].strip().lower(): e for e in raw if e.get("name")}
            _online_index_at = now
            age = now - _ONLINE_DB_PATH.stat().st_mtime
            if age < _ONLINE_DB_TTL:
                return _online_index
        except Exception as e:
            logger.debug("[builtin] 读取本地字体库索引失败: %s", e)

    # 从网络拉取
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_ONLINE_DB_URL)
        if resp.status_code == 200:
            _FONTS_ROOT.mkdir(parents=True, exist_ok=True)
            _ONLINE_DB_PATH.write_bytes(resp.content)
            raw = _json.loads(resp.content)
            _online_index = {e["name"].strip().lower(): e for e in raw if e.get("name")}
            _online_index_at = now
            logger.info("[builtin] 在线字体库更新: %d 条", len(_online_index))
    except Exception as e:
        logger.warning("[builtin] 拉取在线字体库失败: %s", e)

    return _online_index


async def download_font(font_name: str) -> Optional[tuple[str, int]]:
    """
    从 fontInAss 在线字体库下载字体，保存到 downloads 目录。
    下载成功后返回 (文件路径, 0)，否则返回 None。
    """
    idx = _load_online_index()          # 先用同步检查缓存
    db = await _load_online_index()
    key = font_name.lower().strip().lstrip("@")

    entry = db.get(key)
    if not entry:
        for k, v in db.items():
            if k.startswith(key) or key.startswith(k):
                entry = v
                break
    if not entry or not entry.get("url"):
        return None

    _FONTS_DOWNLOAD.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-.]", "_", entry["name"])
    # 尝试常见扩展名
    for ext in (".ttf", ".otf", ".ttc"):
        dst = _FONTS_DOWNLOAD / f"{safe}{ext}"
        if dst.exists():
            logger.debug("[builtin] downloads 缓存命中: %s", dst.name)
            return str(dst), 0

    # 下载
    try:
        logger.info("[builtin] 下载字体: %s → %s", font_name, entry["url"])
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(entry["url"])
        if resp.status_code != 200:
            logger.warning("[builtin] 字体下载失败 HTTP %d: %s", resp.status_code, font_name)
            return None
        # 根据 Content-Type 或 url 后缀确定扩展名
        ct = resp.headers.get("content-type", "")
        if "otf" in ct or entry["url"].lower().endswith(".otf"):
            ext = ".otf"
        elif "ttc" in ct or entry["url"].lower().endswith(".ttc"):
            ext = ".ttc"
        else:
            ext = ".ttf"
        dst = _FONTS_DOWNLOAD / f"{safe}{ext}"
        dst.write_bytes(resp.content)
        logger.info("[builtin] 字体已保存: %s (%d KB)", dst.name, len(resp.content) // 1024)
        return str(dst), 0
    except Exception as e:
        logger.warning("[builtin] 字体下载异常: %s → %s", font_name, e)
        return None
import asyncio
import hashlib
import io
import logging
import os
import re
import time
from collections import defaultdict, OrderedDict
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── 路径：全部挂在 /data/config/fonts 下 ─────────────────────────────────────
_FONTS_ROOT      = Path(os.environ.get("BUILTIN_FONT_DIR", "/data/config/fonts"))
_FONTS_DOWNLOAD  = _FONTS_ROOT / "downloads"           # 在线下载专用子目录
_ONLINE_DB_PATH  = _FONTS_ROOT / "onlineFonts.json"   # 字体库索引本地缓存
_ONLINE_DB_URL   = "https://raw.githubusercontent.com/RiderLty/fontInAss/main/onlineFonts.json"
_ONLINE_DB_TTL   = 3600 * 24   # 24h 更新一次

# ── 结果缓存（md5 → (processed_bytes, expire_ts)）────────────────────────────
_result_cache: "OrderedDict[str, tuple[bytes, float]]" = OrderedDict()
_RESULT_CACHE_MAX = 100
_RESULT_CACHE_TTL = 3600 * 6   # 6h

# ── 字体 bytes 内存缓存（path → bytes，最多 60 条 FIFO）─────────────────────
_font_bytes_cache: "OrderedDict[str, bytes]" = OrderedDict()
_FONT_BYTES_MAX = 60

# ── 本地字体映射（小写名 → (path, index)，5min 重扫）──────────────────────────
_local_map: "dict[str, tuple[str, int]]" = {}
_local_map_at: float = 0.0
_LOCAL_MAP_TTL = 300

# ── 在线字体库索引（小写名 → entry dict）────────────────────────────────────
_online_index: "dict[str, dict]" = {}
_online_index_at: float = 0.0


# ═══════════════════════════════════════════════════════════
# Part 1: ASS 解析（提取字体名 → 字符 unicode 集合映射）
# ═══════════════════════════════════════════════════════════

_RE_STYLE_LINE   = re.compile(r"^Style\s*:", re.MULTILINE)
_RE_DIALOGUE     = re.compile(r"^Dialogue\s*:[^,]*,[^,]*,[^,]*,[^,]*,([^,]*),", re.MULTILINE)
_RE_OVERRIDE_BLK = re.compile(r"\{([^}]*)\}")
_RE_FN           = re.compile(r"\\fn([^\\{}]+)")
_RE_DRAWING_ON   = re.compile(r"\\p\s*[1-9]")
_RE_DRAWING_OFF  = re.compile(r"\\p\s*0")


def _parse_styles(ass_text: str) -> dict[str, str]:
    """从 [V4+ Styles] 段提取 {样式名: 字体名}"""
    styles: dict[str, str] = {}
    in_styles = False
    for line in ass_text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_styles = "[V4" in s and "Styles" in s
            continue
        if not in_styles:
            continue
        if s.startswith("Style:") or s.startswith("Style :"):
            parts = s.split(",")
            if len(parts) >= 2:
                name = parts[0].split(":", 1)[1].strip()
                font = parts[1].strip()
                if name and font:
                    styles[name] = font
    return styles


def analyse_ass(ass_text: str) -> dict[str, set[int]]:
    """
    解析 ASS 字幕文本，返回 {字体名: {使用到的 unicode 码点}}

    处理：
    - Style 段定义默认字体
    - Dialogue 文本里 \\fn 切换字体
    - \\p1..\\p0 绘图块内的内容跳过
    - override tag 本身不记录字符
    """
    styles = _parse_styles(ass_text)
    default_font = styles.get("Default") or (next(iter(styles.values())) if styles else "Arial")
    result: dict[str, set[int]] = defaultdict(set)

    for m in re.finditer(
        r"^Dialogue\s*:[^,]*,[^,]*,[^,]*,([^,]*),(?:[^,]*,){4}(.*)",
        ass_text, re.MULTILINE
    ):
        style_name = m.group(1).strip()
        text = m.group(2)
        cur_font = styles.get(style_name, default_font)
        drawing = False
        pos = 0

        for blk in _RE_OVERRIDE_BLK.finditer(text):
            # 处理 tag 前的纯文本
            plain = text[pos:blk.start()]
            if plain and not drawing:
                for ch in plain:
                    cp = ord(ch)
                    if cp > 0x20:   # 跳过控制字符和空格
                        result[cur_font].add(cp)
            pos = blk.end()

            tags = blk.group(1)
            if _RE_DRAWING_ON.search(tags):
                drawing = True
            if _RE_DRAWING_OFF.search(tags):
                drawing = False
            fn = _RE_FN.search(tags)
            if fn:
                cur_font = fn.group(1).strip() or default_font
                drawing = False

        # tag 之后的剩余文本
        plain = text[pos:]
        if plain and not drawing:
            for ch in plain:
                cp = ord(ch)
                if cp > 0x20:
                    result[cur_font].add(cp)

    return dict(result)



# ═══════════════════════════════════════════════════════════
# Part 4: 字体子集化 + UUEncode + [Fonts] 段写入
# ═══════════════════════════════════════════════════════════

def _load_font_bytes(path: str) -> Optional[bytes]:
    """读取字体文件字节（带内存缓存，FIFO 淘汰）"""
    if path in _font_bytes_cache:
        return _font_bytes_cache[path]
    try:
        data = Path(path).read_bytes()
        _font_bytes_cache[path] = data
        if len(_font_bytes_cache) > _FONT_BYTES_MAX:
            _font_bytes_cache.popitem(last=False)
        return data
    except Exception as e:
        logger.warning("[builtin] 读取字体失败: %s → %s", path, e)
        return None


def _subset_font_sync(font_path: str, face_index: int, unicodes: set[int]) -> Optional[bytes]:
    """
    fonttools 字体子集化（同步，CPU 密集）。
    调用方用 asyncio.to_thread 包裹在线程池中运行。
    """
    try:
        from fontTools.ttLib import TTFont
        from fontTools.subset import Subsetter, Options
    except ImportError:
        logger.error("[builtin] fonttools 未安装，请在 requirements.txt 中添加 fonttools")
        return None
    try:
        font = TTFont(font_path, fontNumber=face_index)
        opts = Options()
        opts.ignore_missing_glyphs = True
        opts.ignore_missing_unicodes = True
        opts.layout_features = ["*"]
        opts.name_IDs = [1, 2, 3, 4, 5, 6]
        sub = Subsetter(options=opts)
        sub.populate(unicodes=sorted(unicodes))
        sub.subset(font)
        buf = io.BytesIO()
        font.save(buf)
        return buf.getvalue()
    except Exception as e:
        logger.warning("[builtin] 子集化失败 %s#%d: %s", font_path, face_index, e)
        return None


def _uuencode_font(font_bytes: bytes, font_name: str) -> str:
    """
    UUEncode 字体字节，格式与 fontInAss 完全兼容。
    每 45 字节原始数据 → 1 行（长度前缀 + 60字符编码）。
    """
    lines = [f"filename: {font_name}"]
    for i in range(0, len(font_bytes), 45):
        chunk = font_bytes[i:i + 45]
        row = bytes([len(chunk) + 32])
        for j in range(0, len(chunk), 3):
            triple = chunk[j:j + 3].ljust(3, b"\x00")
            b0, b1, b2 = triple[0], triple[1], triple[2]
            row += bytes([
                ((b0 >> 2) & 0x3F) + 32,
                (((b0 << 4) | (b1 >> 4)) & 0x3F) + 32,
                (((b1 << 2) | (b2 >> 6)) & 0x3F) + 32,
                (b2 & 0x3F) + 32,
            ])
        lines.append(row.decode("latin-1"))
    lines.append("`")
    return "\n".join(lines) + "\n"


def _insert_fonts_section(ass_text: str, font_entries: dict[str, str]) -> str:
    """将子集化字体写入 ASS [Fonts] 段（有则替换，无则追加）"""
    section_body = "[Fonts]\n" + "".join(font_entries.values())
    ass_text = re.sub(r"\[Fonts\].*?(?=\n\[|\Z)", "", ass_text, flags=re.DOTALL).rstrip()
    return ass_text + "\n\n" + section_body


# ═══════════════════════════════════════════════════════════
# Part 5: 主入口 process_ass_builtin
# ═══════════════════════════════════════════════════════════

async def process_ass_builtin(ass_bytes: bytes) -> tuple[bytes, list[str]]:
    """
    内置字幕子集化主入口。

    Args:
        ass_bytes: 原始 ASS/SSA 字幕字节

    Returns:
        (processed_bytes, missing_fonts)
        - processed_bytes: 嵌入字体后的 ASS 字节（全部失败时退回原始）
        - missing_fonts:   找不到（本地+在线均无）的字体名列表
    """
    # ── 结果缓存命中检查 ──────────────────────────────────────────────────────
    cache_key = hashlib.md5(ass_bytes).hexdigest()
    now = time.monotonic()
    if cache_key in _result_cache:
        cached_bytes, expire_ts = _result_cache[cache_key]
        if now < expire_ts:
            logger.debug("[builtin] 命中结果缓存: %s", cache_key[:8])
            return cached_bytes, []
        del _result_cache[cache_key]

    # ── 解码 ASS 文本（自动检测 BOM / GBK）───────────────────────────────────
    for enc in ("utf-8-sig", "gbk", "latin-1"):
        try:
            ass_text = ass_bytes.decode(enc)
            break
        except Exception:
            continue
    else:
        ass_text = ass_bytes.decode("utf-8", errors="replace")

    # ── Step1: 解析字体字符集 ─────────────────────────────────────────────────
    font_chars = analyse_ass(ass_text)
    if not font_chars:
        logger.info("[builtin] ASS 无字体信息，直接返回原始内容")
        return ass_bytes, []

    logger.info("[builtin] 需要处理的字体: %s", list(font_chars.keys()))

    # ── Step2: 查找字体文件（本地 → downloads → 在线下载）────────────────────
    font_resolved: dict[str, tuple[str, int]] = {}
    missing: list[str] = []

    for font_name in font_chars:
        # 优先查本地（排除 downloads）
        loc = find_local_font(font_name)
        if loc:
            font_resolved[font_name] = loc
            logger.debug("[builtin] 本地命中: %s → %s#%d", font_name, loc[0], loc[1])
            continue
        # 其次查 downloads 目录（已下载的）
        loc = find_downloaded_font(font_name)
        if loc:
            font_resolved[font_name] = loc
            logger.debug("[builtin] downloads 命中: %s → %s", font_name, loc[0])
            continue
        # 最后尝试在线下载
        loc = await download_font(font_name)
        if loc:
            font_resolved[font_name] = loc
        else:
            logger.warning("[builtin] 字体缺失（本地+在线均无）: %s", font_name)
            missing.append(font_name)

    if not font_resolved:
        logger.warning("[builtin] 所有字体均缺失，返回原始字幕")
        return ass_bytes, missing

    # ── Step3: 并行子集化（线程池）──────────────────────────────────────────
    async def _do_subset(fname: str) -> tuple[str, Optional[bytes]]:
        path, idx = font_resolved[fname]
        unicodes = font_chars[fname]
        result = await asyncio.to_thread(_subset_font_sync, path, idx, unicodes)
        return fname, result

    subset_results = await asyncio.gather(*[_do_subset(n) for n in font_resolved])

    # ── Step4: UUEncode + 插入 [Fonts] 段 ───────────────────────────────────
    font_entries: dict[str, str] = {}
    for fname, subset_bytes in subset_results:
        if subset_bytes:
            font_entries[fname] = _uuencode_font(subset_bytes, fname)
        else:
            missing.append(fname)

    if not font_entries:
        logger.warning("[builtin] 子集化全部失败，返回原始字幕")
        return ass_bytes, missing

    ass_text = _insert_fonts_section(ass_text, font_entries)
    logger.info(
        "[builtin] ✅ 完成: 嵌入 %d/%d 个字体，缺失=%s",
        len(font_entries), len(font_chars), missing or "无",
    )

    result_bytes = ass_text.encode("utf-8")

    # ── 写入结果缓存 ─────────────────────────────────────────────────────────
    _result_cache[cache_key] = (result_bytes, now + _RESULT_CACHE_TTL)
    if len(_result_cache) > _RESULT_CACHE_MAX:
        _result_cache.popitem(last=False)

    return result_bytes, missing
