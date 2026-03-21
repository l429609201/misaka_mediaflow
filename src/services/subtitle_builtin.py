# src/services/subtitle_builtin.py
# 内置字幕字体子集化引擎（无需外部 fontInAss 服务）
#
# 支持格式：
#   ASS / SSA  → 直接子集化，字体嵌入 [Fonts] 段
#   SRT        → 先转换为 ASS（使用默认样式），再子集化
#   VTT / 其他 → 透传，原样返回
#
# 工作流程：
#   1. 格式检测
#   2. SRT → ASS 转换（如有必要）
#   3. 解析 ASS，提取字体名 → 字符集映射
#   4. 本地字体扫描（/data/config/fonts，排除 downloads 子目录）
#   5. 本地未命中 → 在线字体库下载 → 保存至 downloads/
#   6. fonttools 子集化 + UUEncode + 写入 [Fonts] 段
#
# 缓存策略：
#   - 按 md5(raw_bytes) 缓存处理结果（6h TTL）
#   - 字体文件 bytes 内存缓存（最多 60 条 FIFO）
#   - 在线字体持久化到 downloads 目录

import asyncio
import hashlib
import io
import logging
import os
import re
import time
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── 路径：全部挂在 /data/config/fonts 下 ─────────────────────────────────────
_FONTS_ROOT     = Path(os.environ.get("BUILTIN_FONT_DIR", "/data/config/fonts"))
_FONTS_DOWNLOAD = _FONTS_ROOT / "downloads"           # 在线下载专用子目录
_ONLINE_DB_PATH = _FONTS_ROOT / "onlineFonts.json"   # 字体库索引本地缓存
_ONLINE_DB_URL  = (
    "https://raw.githubusercontent.com/RiderLty/fontInAss/main/onlineFonts.json"
)
_ONLINE_DB_TTL  = 3600 * 24   # 24h 更新一次

# ── 结果缓存（md5 → (processed_bytes, expire_ts)）────────────────────────────
_result_cache: "OrderedDict[str, tuple[bytes, float]]" = OrderedDict()
_RESULT_CACHE_MAX = 100
_RESULT_CACHE_TTL = 3600 * 6   # 6h

# ── 字体 bytes 内存缓存（path → bytes，最多 60 条 FIFO）─────────────────────
_font_bytes_cache: "OrderedDict[str, bytes]" = OrderedDict()
_FONT_BYTES_MAX = 60

# ── 本地字体映射（小写名 → (path, index)，5min 重扫）─────────────────────────
_local_map: "dict[str, tuple[str, int]]" = {}
_local_map_at: float = 0.0
_LOCAL_MAP_TTL = 300

# ── 在线字体库索引（小写名 → entry dict）────────────────────────────────────
_online_index: "dict[str, dict]" = {}
_online_index_at: float = 0.0

_FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}


# ═══════════════════════════════════════════════════════════
# Part 0: 格式检测 & SRT → ASS 转换
# ═══════════════════════════════════════════════════════════

def _detect_format(raw: bytes) -> str:
    """
    检测字幕格式。
    返回: 'ass' | 'srt' | 'vtt' | 'unknown'
    """
    # 取前 512 字节做检测
    head = raw[:512]
    try:
        text = head.decode("utf-8-sig", errors="replace")
    except Exception:
        text = ""

    text_lower = text.lower().lstrip()
    if text_lower.startswith("webvtt"):
        return "vtt"
    if "[script info]" in text_lower or "[v4+ styles]" in text_lower or "[events]" in text_lower:
        return "ass"
    # SRT 特征：纯数字行 + 时间轴 "00:00:00,000 --> 00:00:00,000"
    if re.search(r"\d+:\d+:\d+,\d+\s*-->\s*\d+:\d+:\d+,\d+", text):
        return "srt"
    return "unknown"


_SRT_BLOCK = re.compile(
    r"(\d+)\r?\n"
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})[^\r\n]*\r?\n"
    r"((?:.*\r?\n)*?)"
    r"(?=\r?\n|\Z)",
    re.MULTILINE,
)
_SRT_TAG   = re.compile(r"<[^>]+>")
_SRT_TIME  = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def _srt_time_to_ass(t: str) -> str:
    """'00:01:23,456'  →  '0:01:23.46'  (ASS 格式，百分秒)"""
    m = _SRT_TIME.match(t)
    if not m:
        return "0:00:00.00"
    h, mn, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
    cs = ms // 10  # centiseconds
    return f"{h}:{mn:02d}:{s:02d}.{cs:02d}"


def _strip_srt_tags(text: str) -> str:
    """去掉 <b> <i> <u> <font ...> 等 HTML 标签"""
    return _SRT_TAG.sub("", text).strip()


def srt_to_ass(srt_text: str, font_name: str = "Arial", font_size: int = 48) -> str:
    """
    将 SRT 字幕转换为 ASS 格式。
    采用简洁默认样式，字体可由调用方指定（默认 Arial 48px 白色）。
    """
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.rstrip()]
    for m in _SRT_BLOCK.finditer(srt_text):
        start = _srt_time_to_ass(m.group(2))
        end   = _srt_time_to_ass(m.group(3))
        raw_text = m.group(4).strip()
        # 多行合并为 \N
        text_lines = [_strip_srt_tags(l) for l in raw_text.splitlines() if l.strip()]
        text = r"\N".join(text_lines)
        if text:
            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"



# ═══════════════════════════════════════════════════════════
# Part 1: ASS 解析（提取字体名 → 字符 unicode 集合映射）
# ═══════════════════════════════════════════════════════════

_RE_OVERRIDE_BLK = re.compile(r"\{([^}]*)\}")
_RE_FN           = re.compile(r"\\fn([^\\{}]+)")
_RE_DRAWING_ON   = re.compile(r"\\p\s*[1-9]")
_RE_DRAWING_OFF  = re.compile(r"\\p\s*0")


def _parse_styles(ass_text: str) -> dict:
    """从 [V4+ Styles] 段提取 {样式名: 字体名}"""
    styles: dict = {}
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


def analyse_ass(ass_text: str) -> dict:
    """
    解析 ASS 字幕文本，返回 {字体名: {使用到的 unicode 码点}}

    处理：
    - Style 段定义默认字体
    - Dialogue 文本里 \\fn 切换字体
    - \\p1..\\p0 绘图块内的内容跳过
    - override tag 本身不记录字符
    """
    styles = _parse_styles(ass_text)
    default_font = styles.get("Default") or (
        next(iter(styles.values())) if styles else "Arial"
    )
    result: dict = defaultdict(set)

    for m in re.finditer(
        r"^Dialogue\s*:[^,]*,[^,]*,[^,]*,([^,]*),(?:[^,]*,){4}(.*)",
        ass_text, re.MULTILINE,
    ):
        style_name = m.group(1).strip()
        text = m.group(2)
        cur_font = styles.get(style_name, default_font)
        drawing = False
        pos = 0

        for blk in _RE_OVERRIDE_BLK.finditer(text):
            plain = text[pos:blk.start()]
            if plain and not drawing:
                for ch in plain:
                    cp = ord(ch)
                    if cp > 0x20:
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

        plain = text[pos:]
        if plain and not drawing:
            for ch in plain:
                cp = ord(ch)
                if cp > 0x20:
                    result[cur_font].add(cp)

    return dict(result)


# ═══════════════════════════════════════════════════════════
# Part 2: 本地字体库扫描（排除 downloads 子目录）
# ═══════════════════════════════════════════════════════════

def _read_font_names_from_file(path: Path) -> list:
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
                    if rec.nameID in (1, 4):
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


def _scan_local_fonts() -> dict:
    """
    扫描 _FONTS_ROOT 目录下的所有字体文件（递归），
    但排除 downloads 子目录。
    返回 {小写字体名: (文件绝对路径, face_index)}
    """
    result: dict = {}
    if not _FONTS_ROOT.exists():
        return result
    for path in _FONTS_ROOT.rglob("*"):
        if _FONTS_DOWNLOAD in path.parents or path == _FONTS_DOWNLOAD:
            continue
        if path.suffix.lower() not in _FONT_EXTS:
            continue
        for name, idx in _read_font_names_from_file(path):
            if name not in result:
                result[name] = (str(path), idx)
    logger.info("[builtin] 本地字体扫描完成: %d 条（排除 downloads）", len(result))
    return result


def _get_local_map() -> dict:
    global _local_map, _local_map_at
    now = time.monotonic()
    if _local_map and (now - _local_map_at) < _LOCAL_MAP_TTL:
        return _local_map
    _local_map = _scan_local_fonts()
    _local_map_at = now
    return _local_map


def _find_in_map(name_lower: str, fm: dict) -> Optional[tuple]:
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


def find_local_font(font_name: str) -> Optional[tuple]:
    """查找本地字体（不含 downloads）。返回 (绝对路径, face_index) 或 None。"""
    return _find_in_map(font_name.lower().strip(), _get_local_map())


def find_downloaded_font(font_name: str) -> Optional[tuple]:
    """在 downloads 目录中查找已下载的字体（单独扫描，不缓存）。"""
    if not _FONTS_DOWNLOAD.exists():
        return None
    dm: dict = {}
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

async def _load_online_index() -> dict:
    """
    加载 fontInAss 在线字体库索引。
    优先读本地缓存文件（24h 内有效），过期后重新拉取。
    索引格式: {小写字体名: {\"name\": str, \"url\": str}}
    """
    global _online_index, _online_index_at
    now = time.monotonic()
    if _online_index and (now - _online_index_at) < _ONLINE_DB_TTL:
        return _online_index

    import json as _json

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


async def download_font(font_name: str) -> Optional[tuple]:
    """
    从 fontInAss 在线字体库下载字体，保存到 downloads 目录。
    下载成功后返回 (文件路径, 0)，否则返回 None。
    """
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
    for ext in (".ttf", ".otf", ".ttc"):
        dst = _FONTS_DOWNLOAD / f"{safe}{ext}"
        if dst.exists():
            logger.debug("[builtin] downloads 缓存命中: %s", dst.name)
            return str(dst), 0

    try:
        logger.info("[builtin] 下载字体: %s → %s", font_name, entry["url"])
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(entry["url"])
        if resp.status_code != 200:
            logger.warning("[builtin] 字体下载失败 HTTP %d: %s", resp.status_code, font_name)
            return None
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


def _subset_font_sync(font_path: str, face_index: int, unicodes: set) -> Optional[bytes]:
    """
    fonttools 字体子集化（同步，CPU 密集）。
    调用方用 asyncio.to_thread 包裹在线程池中运行。
    """
    try:
        from fontTools.ttLib import TTFont
        from fontTools.subset import Subsetter, Options
    except ImportError:
        logger.error("[builtin] fonttools 未安装，请在 requirements.txt 添加 fonttools>=4.51.0")
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


def _insert_fonts_section(ass_text: str, font_entries: dict) -> str:
    """将子集化字体写入 ASS [Fonts] 段（有则替换，无则追加）"""
    section_body = "[Fonts]\n" + "".join(font_entries.values())
    ass_text = re.sub(r"\[Fonts\].*?(?=\n\[|\Z)", "", ass_text, flags=re.DOTALL).rstrip()
    return ass_text + "\n\n" + section_body


# ═══════════════════════════════════════════════════════════
# Part 5: 主入口 process_subtitle_builtin（支持 ASS/SRT/VTT）
# ═══════════════════════════════════════════════════════════

async def _process_ass_content(ass_text: str, raw_bytes: bytes) -> tuple:
    """
    ASS 内容子集化核心逻辑。
    返回 (result_bytes, missing_fonts, content_type)
    """
    font_chars = analyse_ass(ass_text)
    if not font_chars:
        logger.info("[builtin] ASS 无字体信息，直接返回原始内容")
        return raw_bytes, [], "text/x-ssa; charset=utf-8"

    logger.info("[builtin] 需要处理的字体: %s", list(font_chars.keys()))

    font_resolved: dict = {}
    missing: list = []

    for font_name in font_chars:
        loc = find_local_font(font_name)
        if loc:
            font_resolved[font_name] = loc
            logger.debug("[builtin] 本地命中: %s → %s", font_name, loc[0])
            continue
        loc = find_downloaded_font(font_name)
        if loc:
            font_resolved[font_name] = loc
            logger.debug("[builtin] downloads 命中: %s", font_name)
            continue
        loc = await download_font(font_name)
        if loc:
            font_resolved[font_name] = loc
        else:
            logger.warning("[builtin] 字体缺失（本地+在线均无）: %s", font_name)
            missing.append(font_name)

    if not font_resolved:
        logger.warning("[builtin] 所有字体均缺失，返回原始字幕")
        return raw_bytes, missing, "text/x-ssa; charset=utf-8"

    async def _do_subset(fname: str) -> tuple:
        path, idx = font_resolved[fname]
        unicodes = font_chars[fname]
        result = await asyncio.to_thread(_subset_font_sync, path, idx, unicodes)
        return fname, result

    subset_results = await asyncio.gather(*[_do_subset(n) for n in font_resolved])

    font_entries: dict = {}
    for fname, subset_bytes in subset_results:
        if subset_bytes:
            font_entries[fname] = _uuencode_font(subset_bytes, fname)
        else:
            missing.append(fname)

    if not font_entries:
        logger.warning("[builtin] 子集化全部失败，返回原始字幕")
        return raw_bytes, missing, "text/x-ssa; charset=utf-8"

    ass_out = _insert_fonts_section(ass_text, font_entries)
    logger.info(
        "[builtin] ✅ 完成: 嵌入 %d/%d 个字体，缺失=%s",
        len(font_entries), len(font_chars), missing or "无",
    )
    return ass_out.encode("utf-8"), missing, "text/x-ssa; charset=utf-8"


async def process_subtitle_builtin(raw_bytes: bytes) -> tuple:
    """
    内置字幕子集化主入口，支持 ASS / SRT / VTT / 其他格式。

    Args:
        raw_bytes: 原始字幕字节（任意格式）

    Returns:
        (processed_bytes, missing_fonts, content_type)
        - processed_bytes : 处理后的字幕字节（失败时退回原始）
        - missing_fonts   : 缺失字体列表（VTT/unknown 时为空）
        - content_type    : 响应 Content-Type
    """
    cache_key = hashlib.md5(raw_bytes).hexdigest()
    now = time.monotonic()
    if cache_key in _result_cache:
        cached_bytes, expire_ts = _result_cache[cache_key]
        if now < expire_ts:
            logger.debug("[builtin] 命中结果缓存: %s", cache_key[:8])
            return cached_bytes, [], "text/x-ssa; charset=utf-8"
        del _result_cache[cache_key]

    fmt = _detect_format(raw_bytes)
    logger.debug("[builtin] 检测到字幕格式: %s", fmt)

    if fmt == "vtt":
        logger.info("[builtin] VTT 格式，透传原始内容")
        return raw_bytes, [], "text/vtt; charset=utf-8"

    if fmt == "unknown":
        logger.info("[builtin] 未知字幕格式，透传原始内容")
        return raw_bytes, [], "text/plain; charset=utf-8"

    # ── 解码文本（ASS 或 SRT）────────────────────────────────────────────────
    for enc in ("utf-8-sig", "gbk", "latin-1"):
        try:
            text = raw_bytes.decode(enc)
            break
        except Exception:
            continue
    else:
        text = raw_bytes.decode("utf-8", errors="replace")

    # ── SRT → ASS 转换 ───────────────────────────────────────────────────────
    if fmt == "srt":
        logger.info("[builtin] SRT 格式，转换为 ASS 再子集化")
        text = srt_to_ass(text)

    result_bytes, missing, ct = await _process_ass_content(text, raw_bytes)

    _result_cache[cache_key] = (result_bytes, now + _RESULT_CACHE_TTL)
    if len(_result_cache) > _RESULT_CACHE_MAX:
        _result_cache.popitem(last=False)

    return result_bytes, missing, ct


# 向后兼容旧接口名（subtitle_service.py 中使用的是 process_ass_builtin）
async def process_ass_builtin(ass_bytes: bytes) -> tuple:
    """兼容旧调用，委托给 process_subtitle_builtin。"""
    result_bytes, missing, _ = await process_subtitle_builtin(ass_bytes)
    return result_bytes, missing
