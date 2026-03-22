# src/services/subtitle_builtin.py
# 内置字幕字体子集化引擎（参考 MkvAutoSubset 改进）
#
# 支持格式：
#   ASS / SSA  → 解析 Bold/Italic/\r 标签，三层 fallback 字体匹配，精确子集化
#   SRT        → 先转换为 ASS，再子集化
#   VTT / 其他 → 透传，原样返回
#
# 与 MkvAutoSubset 相比的关键对齐点：
#   1. analyse_ass：追踪 \b \i \r 状态，key=字体名^Regular/Bold/Italic/Bold Italic
#   2. 字体扫描：读取 nameID 1/2/4/6（Family/Subfamily/Full/PostScript）
#   3. 三层 fallback：精确→Regular fallback→大小写 fallback
#   4. reMap：同一字体文件的字符集合并，只子集化一次
#   5. 字符集补全：有数字时加 0123456789，总加 \u0020 \u00a0

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

# ── 路径配置 ──────────────────────────────────────────────────────────────────
_FONTS_ROOT     = Path(os.environ.get("BUILTIN_FONT_DIR", "/app/config/fonts"))
_FONTS_DOWNLOAD = _FONTS_ROOT / "downloads"
_ONLINE_DB_PATH = _FONTS_ROOT / "onlineFonts.json"
_ONLINE_DB_URL  = (
    "https://raw.githubusercontent.com/RiderLty/fontInAss/main/onlineFonts.json"
)
_ONLINE_DB_TTL  = 3600 * 24   # 24h

# ── 缓存 ──────────────────────────────────────────────────────────────────────
_result_cache: "OrderedDict[str, tuple[bytes, float]]" = OrderedDict()
_RESULT_CACHE_MAX = 100
_RESULT_CACHE_TTL = 3600 * 6   # 6h

# ── 本地字体库（5min 重扫）────────────────────────────────────────────────────
# 每条记录: {"names": set[str], "subfamily": set[str], "path": str, "idx": int}
_local_db: list = []
_local_db_at: float = 0.0
_LOCAL_DB_TTL = 300

# ── 在线字体库索引 ────────────────────────────────────────────────────────────
_online_index: "dict[str, dict]" = {}
_online_index_at: float = 0.0

_FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}

# ── 字体 variant（MkvAutoSubset 相同格式）────────────────────────────────────
_VARIANT_REGULAR     = "Regular"
_VARIANT_BOLD        = "Bold"
_VARIANT_ITALIC      = "Italic"
_VARIANT_BOLD_ITALIC = "Bold Italic"

# 分隔符：用于从 "FontName Bold" 中提取 "Bold" 作为 Subfamily 匹配
_FONT_NAME_SEPS = [" ", "-"]


# ═══════════════════════════════════════════════════════════
# Part 0: 格式检测 & SRT → ASS 转换
# ═══════════════════════════════════════════════════════════

def _detect_format(raw: bytes) -> str:
    """检测字幕格式：返回 'ass' | 'srt' | 'vtt' | 'unknown'"""
    head = raw[:512]
    try:
        text = head.decode("utf-8-sig", errors="replace")
    except Exception:
        text = ""
    tl = text.lower().lstrip()
    if tl.startswith("webvtt"):
        return "vtt"
    if "[script info]" in tl or "[v4+ styles]" in tl or "[events]" in tl:
        return "ass"
    if re.search(r"\d+:\d+:\d+,\d+\s*-->\s*\d+:\d+:\d+,\d+", text):
        return "srt"
    return "unknown"


_SRT_BLOCK = re.compile(
    r"\d+\r?\n"
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})[^\r\n]*\r?\n"
    r"((?:.*\r?\n)*?)"
    r"(?=\r?\n|\Z)",
    re.MULTILINE,
)
_SRT_TAG  = re.compile(r"<[^>]+>")
_SRT_TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def _srt_time_to_ass(t: str) -> str:
    m = _SRT_TIME.match(t)
    if not m:
        return "0:00:00.00"
    h, mn, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
    return f"{h}:{mn:02d}:{s:02d}.{ms // 10:02d}"


def srt_to_ass(srt_text: str, font_name: str = "Arial", font_size: int = 48) -> str:
    """SRT → ASS 转换（简洁默认样式）"""
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n"
        "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,"
        "&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,20,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    )
    lines = [header]
    for m in _SRT_BLOCK.finditer(srt_text):
        start = _srt_time_to_ass(m.group(1))
        end   = _srt_time_to_ass(m.group(2))
        raw_text = m.group(3).strip()
        text_parts = [_SRT_TAG.sub("", l) for l in raw_text.splitlines() if l.strip()]
        text = r"\N".join(text_parts)
        if text:
            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"



# ═══════════════════════════════════════════════════════════
# Part 1: ASS 解析（对齐 MkvAutoSubset：Bold/Italic/\r 追踪）
# ═══════════════════════════════════════════════════════════
#
# key 格式与 MkvAutoSubset 相同：
#   "字体名^Regular"      — 普通文本
#   "字体名^Bold"         — \b1 或 Style.Bold=1
#   "字体名^Italic"       — \i1 或 Style.Italic=1
#   "字体名^Bold Italic"  — 同时 Bold+Italic

_RE_OVR    = re.compile(r"\{([^}]*)\}")   # 整个 override block {...}
_RE_FN     = re.compile(r"\\fn([^\\{}]+)")
_RE_DRAW_ON  = re.compile(r"\\p\s*[1-9]")
_RE_DRAW_OFF = re.compile(r"\\p\s*0")
_RE_B_TAG  = re.compile(r"\\b(\d+)")      # \b0 \b1 \b700…
_RE_I_TAG  = re.compile(r"\\i(\d)")
_RE_R_TAG  = re.compile(r"\\r(.*?)(?=\\|\}|$)")  # \r 或 \rStyleName
_RE_HAS_DIGIT = re.compile(r"\d")


def _parse_styles(ass_text: str) -> dict:
    """
    从 [V4+ Styles] 解析每个样式。
    Style 字段顺序（v4+）：
      Name, Fontname, Fontsize, ..., Bold, Italic, Underline, ...
    返回 {样式名: (字体名, is_bold: bool, is_italic: bool)}
    """
    styles: dict = {}
    in_styles = False
    for line in ass_text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_styles = ("[V4" in s and "Styles" in s)
            continue
        if not in_styles:
            continue
        if not (s.startswith("Style:") or s.startswith("Style :")):
            continue
        parts = [p.strip() for p in s.split(":", 1)[1].split(",")]
        if len(parts) < 9:
            continue
        # Format: Name(0), Fontname(1), Fontsize(2), ... Bold(7), Italic(8)
        name   = parts[0].strip()
        font   = parts[1].strip()
        # Bold/Italic 字段：-1 或 1 表示 True；0 表示 False
        try:
            is_bold   = int(parts[7]) != 0
        except (ValueError, IndexError):
            is_bold = False
        try:
            is_italic = int(parts[8]) != 0
        except (ValueError, IndexError):
            is_italic = False
        if name and font:
            styles[name] = (font, is_bold, is_italic)
    return styles


def _variant_key(bold: bool, italic: bool) -> str:
    """根据 Bold/Italic 状态返回 variant 字符串"""
    if bold and italic:
        return _VARIANT_BOLD_ITALIC
    if bold:
        return _VARIANT_BOLD
    if italic:
        return _VARIANT_ITALIC
    return _VARIANT_REGULAR


def analyse_ass(ass_text: str) -> dict:
    """
    解析 ASS 字幕，返回 {"字体名^Variant": set(unicode_codepoints)}

    改进点（相对旧版）：
    - 追踪 \\b（Bold）、\\i（Italic）tag 状态变化
    - 处理 \\r（重置样式）和 \\r<StyleName>（切换样式）
    - 字符集额外补全：总加 \\u0020 \\u00a0，有数字时加 0123456789
    - \\p 绘图块过滤
    - @ 前缀字体名去 @ 处理
    """
    styles = _parse_styles(ass_text)
    default_style = styles.get("Default") or (
        next(iter(styles.values())) if styles else ("Arial", False, False)
    )

    # 累积 {key: list[str]}，最后 join 转 set(codepoints)，避免 O(n²) 字符串拼接
    char_map: dict = defaultdict(list)

    for m in re.finditer(
        r"^Dialogue\s*:[^,]*,[^,]*,[^,]*,([^,]*),(?:[^,]*,){4}(.*)",
        ass_text, re.MULTILINE,
    ):
        style_name = m.group(1).strip()
        text = m.group(2)

        # 初始化状态：从 Style 定义中读取
        st = styles.get(style_name, default_style)
        cur_font, cur_bold, cur_italic = st[0], st[1], st[2]
        # 保存行初始状态（用于 \r 重置）
        orig_font, orig_bold, orig_italic = cur_font, cur_bold, cur_italic

        drawing = False
        pos = 0

        for blk in _RE_OVR.finditer(text):
            # 处理 tag 前的纯文本
            plain = text[pos:blk.start()]
            if plain and not drawing:
                fn_key = f"{cur_font.lstrip('@')}^{_variant_key(cur_bold, cur_italic)}"
                # 去掉 ASS 换行标记 \N \n（两字符序列）
                char_map[fn_key].append(plain.replace("\\N", "").replace("\\n", ""))
            pos = blk.end()

            tags = blk.group(1)

            # ── \p 绘图块 ─────────────────────────────────────────────────
            if _RE_DRAW_ON.search(tags):
                drawing = True
            if _RE_DRAW_OFF.search(tags):
                drawing = False

            # ── \fn 字体切换 ──────────────────────────────────────────────
            fn = _RE_FN.search(tags)
            if fn:
                fn_val = fn.group(1).strip()
                cur_font = fn_val if fn_val else orig_font
                drawing = False   # \fn 同时退出绘图模式

            # ── \b Bold ─────────────────────────────────────────────────
            # \b0 → Regular；\b1 或字重值（≥100）→ Bold
            for bm in _RE_B_TAG.finditer(tags):
                cur_bold = int(bm.group(1)) != 0

            # ── \i Italic ─────────────────────────────────────────────────
            im = _RE_I_TAG.search(tags)
            if im:
                cur_italic = im.group(1) == "1"

            # ── \r 样式重置 ───────────────────────────────────────────────
            rm = _RE_R_TAG.search(tags)
            if rm:
                style_ref = rm.group(1).strip()
                if style_ref == "*Default":
                    style_ref = "Default"
                if not style_ref:
                    # \r — 重置到当前行原始样式
                    cur_font, cur_bold, cur_italic = orig_font, orig_bold, orig_italic
                elif style_ref in styles:
                    rs = styles[style_ref]
                    cur_font, cur_bold, cur_italic = rs[0], rs[1], rs[2]
                # else: 样式不存在，忽略

        # 剩余文本
        plain = text[pos:]
        if plain and not drawing:
            fn_key = f"{cur_font.lstrip('@')}^{_variant_key(cur_bold, cur_italic)}"
            char_map[fn_key].append(plain.replace("\\N", "").replace("\\n", ""))

    # 转换为 codepoint set，并补全字符集
    result: dict = {}
    for key, chunks in char_map.items():
        chars = "".join(chunks)
        if not chars:
            continue
        # 有数字 → 补全 0-9（MkvAutoSubset 同款逻辑）
        if _RE_HAS_DIGIT.search(chars):
            chars += "0123456789"
        # 总是加 空格 + 非断行空格（MkvAutoSubset："\u0020\u00a0"）
        codepoints = {ord(c) for c in chars}
        codepoints |= {0x20, 0xA0}   # 空格、非断行空格
        codepoints.discard(0)         # 去掉 NUL
        if codepoints:
            result[key] = codepoints
    return result


# ═══════════════════════════════════════════════════════════
# Part 2: 本地字体库扫描（对齐 MkvAutoSubset：nameID 1/2/4/6 + 三层 fallback）
# ═══════════════════════════════════════════════════════════
#
# 每条 FontRecord:
#   names     : set[str] — Family(1) + Full(4) + PostScript(6)（大小写保留原始）
#   subfamily : set[str] — Subfamily(2)（Regular/Bold/Italic/Bold Italic…）
#   path      : str      — 字体文件绝对路径
#   idx       : int      — face index（TTC 集合用）

def _read_font_records(path: Path) -> list:
    """
    读取字体文件的所有 font 元数据，返回 [FontRecord, ...]。
    FontRecord = {"names": set, "subfamily": set, "path": str, "idx": int}
    """
    try:
        from fontTools.ttLib import TTFont, TTCollection
    except ImportError:
        logger.warning("[builtin] fonttools 未安装，无法扫描字体")
        return []

    records = []
    ext = path.suffix.lower()

    def _extract_record(font, idx: int) -> Optional[dict]:
        names_set: set = set()
        subfamily_set: set = set()
        for rec in font["name"].names:
            if rec.nameID not in (1, 2, 4, 6):
                continue
            try:
                val = rec.toUnicode().strip()
            except Exception:
                continue
            if not val:
                continue
            if rec.nameID == 2:
                subfamily_set.add(val)
            else:
                names_set.add(val)
        if not names_set:
            return None
        # 若 subfamily 为空，尝试从 Full name 尾部推断
        if not subfamily_set:
            subfamily_set.add("Regular")
        return {"names": names_set, "subfamily": subfamily_set,
                "path": str(path), "idx": idx}

    try:
        if ext in (".ttc", ".otc"):
            col = TTCollection(str(path))
            for idx in range(len(col.fonts)):
                font = TTFont(str(path), fontNumber=idx, lazy=True)
                rec = _extract_record(font, idx)
                if rec:
                    records.append(rec)
                font.close()
        else:
            font = TTFont(str(path), lazy=True)
            rec = _extract_record(font, 0)
            if rec:
                records.append(rec)
            font.close()
    except Exception as e:
        logger.debug("[builtin] 跳过字体文件 %s: %s", path.name, e)
    return records


def _scan_fonts(root: Path, exclude: Optional[Path] = None) -> list:
    """
    递归扫描目录，返回所有 FontRecord 列表。
    exclude 目录会被跳过（用于排除 downloads）。
    """
    db: list = []
    if not root.exists():
        return db
    for p in root.rglob("*"):
        if exclude and (exclude in p.parents or p == exclude):
            continue
        if p.suffix.lower() not in _FONT_EXTS:
            continue
        db.extend(_read_font_records(p))
    logger.info("[builtin] 字体扫描完成: %d 个 face（目录: %s）", len(db), root)
    return db


def _get_local_db() -> list:
    global _local_db, _local_db_at
    now = time.monotonic()
    if _local_db and (now - _local_db_at) < _LOCAL_DB_TTL:
        return _local_db
    _local_db = _scan_fonts(_FONTS_ROOT, exclude=_FONTS_DOWNLOAD)
    _local_db_at = now
    return _local_db


# downloads 目录缓存（30s TTL，比 local_db 更短以感知新下载的字体）
_dl_db: list = []
_dl_db_at: float = 0.0
_DL_DB_TTL = 30


def _get_downloads_db() -> list:
    """扫描 downloads 目录，带 30s 缓存，避免同一次字幕处理重复全量扫描。"""
    global _dl_db, _dl_db_at
    now = time.monotonic()
    if _dl_db is not None and (now - _dl_db_at) < _DL_DB_TTL:
        return _dl_db
    _dl_db = _scan_fonts(_FONTS_DOWNLOAD)
    _dl_db_at = now
    return _dl_db


def _invalidate_downloads_db() -> None:
    """下载新字体后调用，立即使 downloads 缓存失效。"""
    global _dl_db_at
    _dl_db_at = 0.0


def _match_record(rec: dict, name: str, subfamily: str,
                  case_insensitive: bool = False) -> bool:
    """
    判断 FontRecord 是否匹配 (name, subfamily)。

    匹配逻辑（两路）：
      路径 A：直接匹配 — name 在 rec["names"] 中 且 subfamily 在 rec["subfamily"] 中
      路径 B：分隔符拆分 — 对 rec["names"] 里的每个名字尝试拆分，
              用"主名"匹配 name，用"尾部"匹配 subfamily
              （解决字体文件 Family name 含字重后缀的情况，
               如 Family="Source Han Sans CN Bold"，ASS 里写 "Source Han Sans CN"，
               subfamily="Bold"，此时无法直接匹配，拆分后可以匹配）
    """
    target_names = rec["names"]
    target_sub   = rec["subfamily"]

    def neq(a: str, b: str) -> bool:
        return a.lower() == b.lower() if case_insensitive else a == b

    # 路径 A：直接名字 + subfamily 匹配
    if any(neq(n, name) for n in target_names):
        if any(neq(sf, subfamily) for sf in target_sub):
            return True

    # 路径 B：分隔符拆分（对记录里的名字拆，不是对 ASS 字体名拆）
    # 例：记录名 "Source Han Sans CN Bold" 拆为 "Source Han Sans CN" + "Bold"
    #     ASS 字体名 "Source Han Sans CN"，subfamily "Bold" → 匹配
    for rec_name in target_names:
        for sep in _FONT_NAME_SEPS:
            idx = rec_name.rfind(sep)
            if idx <= 0 or idx >= len(rec_name) - 1:
                continue
            base = rec_name[:idx]    # 分隔符前的主名
            tail = rec_name[idx + 1:]  # 分隔符后的 Subfamily 候选
            if neq(base, name) and neq(tail, subfamily):
                return True

    return False


def find_font(name: str, subfamily: str, db: list) -> Optional[tuple]:
    """
    三层 fallback 字体查找（对齐 MkvAutoSubset matchFonts）：
      层0: 精确匹配 name + subfamily
      层1: Bold/Italic → Regular fallback
      层2a: 大小写不敏感精确
      层2b: 大小写不敏感 + Regular fallback
    返回 (path, face_index) 或 None。
    """
    # 层0: 精确
    for rec in db:
        if _match_record(rec, name, subfamily):
            return rec["path"], rec["idx"]

    # 层1: Regular fallback
    if subfamily != _VARIANT_REGULAR:
        for rec in db:
            if _match_record(rec, name, _VARIANT_REGULAR):
                logger.debug("[builtin] fb1 Regular: %s^%s → %s", name, subfamily, rec["path"])
                return rec["path"], rec["idx"]

    # 层2a: 大小写不敏感精确
    for rec in db:
        if _match_record(rec, name, subfamily, case_insensitive=True):
            logger.debug("[builtin] fb2a 大小写: %s^%s → %s", name, subfamily, rec["path"])
            return rec["path"], rec["idx"]

    # 层2b: 大小写不敏感 + Regular fallback
    if subfamily != _VARIANT_REGULAR:
        for rec in db:
            if _match_record(rec, name, _VARIANT_REGULAR, case_insensitive=True):
                logger.debug("[builtin] fb2b 大小写+Regular: %s^%s → %s",
                             name, subfamily, rec["path"])
                return rec["path"], rec["idx"]

    return None


def find_local_font(name: str, subfamily: str = _VARIANT_REGULAR) -> Optional[tuple]:
    """在本地字体库（排除 downloads）中查找字体，三层 fallback。"""
    return find_font(name, subfamily, _get_local_db())


def find_downloaded_font(name: str, subfamily: str = _VARIANT_REGULAR) -> Optional[tuple]:
    """在 downloads 目录中查找字体，三层 fallback。"""
    return find_font(name, subfamily, _get_downloads_db())


# ═══════════════════════════════════════════════════════════
# Part 3: 在线字体库（fontInAss onlineFonts.json）
# ═══════════════════════════════════════════════════════════

def _parse_online_index(raw) -> dict:
    """
    解析 onlineFonts.json，兼容新旧两种格式。

    旧格式（已废弃）: [{"name": "...", "url": "..."}, ...]
      → 返回 {小写字体名: {"name": ..., "url": ..., "_fmt": "old"}}

    新格式（当前）:   [hosts_list, name_index_map, font_data_list]
      hosts_list    : ["https://cdn1.../", "https://cdn2.../"]
      name_index_map: {"字体名小写": [行号, ...], ...}  ← onlineMapIndex
      font_data_list: [{"path": "相对路径", "index": face_idx, "weight": ...,
                        "bold": bool, "italic": bool, ...}, ...]
      → 返回 {小写字体名: {"_fmt": "new", "_hosts": [...], "_candidates": [data_item,...]}}

    下载逻辑在 download_font() 中处理。
    """
    if not isinstance(raw, list) or len(raw) == 0:
        return {}

    # ── 旧格式：第一个元素是 dict 且含 "name" key ────────────────────────────
    if isinstance(raw[0], dict) and "name" in raw[0]:
        return {e["name"].strip().lower(): {**e, "_fmt": "old"}
                for e in raw if isinstance(e, dict) and e.get("name")}

    # ── 新格式：第一个元素是 list（CDN hosts）────────────────────────────────
    # 结构：raw[0]=hosts, raw[1]=name_index_map, raw[2]=font_data_list
    if not (isinstance(raw[0], list) and len(raw) >= 3
            and isinstance(raw[1], dict) and isinstance(raw[2], list)):
        logger.debug("[builtin] onlineFonts.json 格式无法识别，跳过")
        return {}

    hosts: list = raw[0]
    name_index_map: dict = raw[1]
    font_data_list: list = raw[2]

    result: dict = {}
    for name_lower, row_indices in name_index_map.items():
        candidates = []
        for idx in row_indices:
            if 0 <= idx < len(font_data_list):
                candidates.append(font_data_list[idx])
        if candidates:
            result[name_lower] = {
                "_fmt": "new",
                "_hosts": hosts,
                "_candidates": candidates,
            }
    logger.debug("[builtin] onlineFonts.json 新格式解析完成: %d 个字体可供下载", len(result))
    return result


async def _load_online_index() -> dict:
    """24h 更新一次的在线字体库索引，索引格式: {小写名: entry_dict}"""
    global _online_index, _online_index_at
    now = time.monotonic()
    if _online_index and (now - _online_index_at) < _ONLINE_DB_TTL:
        return _online_index

    import json as _json

    if _ONLINE_DB_PATH.exists():
        try:
            raw = _json.loads(_ONLINE_DB_PATH.read_bytes())
            parsed = _parse_online_index(raw)
            _online_index_at = now
            age = now - _ONLINE_DB_PATH.stat().st_mtime
            if age < _ONLINE_DB_TTL:
                _online_index = parsed
                return _online_index
        except Exception as e:
            logger.debug("[builtin] 读取本地字体库索引失败: %s", e)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_ONLINE_DB_URL)
        if resp.status_code == 200:
            _FONTS_ROOT.mkdir(parents=True, exist_ok=True)
            _ONLINE_DB_PATH.write_bytes(resp.content)
            import json as _json2
            raw = _json2.loads(resp.content)
            _online_index = _parse_online_index(raw)
            _online_index_at = now
            logger.debug("[builtin] 在线字体库索引刷新: %d 条可用", len(_online_index))
    except Exception as e:
        logger.debug("[builtin] 拉取在线字体库失败: %s", e)
    return _online_index


def _select_best_candidate(candidates: list, is_bold: bool = False,
                           is_italic: bool = False) -> Optional[dict]:
    """
    从候选字体列表中选出最匹配 bold/italic 的 face。
    优先精确匹配，次选 Regular。
    """
    if not candidates:
        return None
    # 精确匹配 bold + italic
    for c in candidates:
        if bool(c.get("bold")) == is_bold and bool(c.get("italic")) == is_italic:
            return c
    # Regular fallback（bold=False, italic=False）
    for c in candidates:
        if not c.get("bold") and not c.get("italic"):
            return c
    # 返回第一个
    return candidates[0]


async def download_font(font_name: str, is_bold: bool = False,
                        is_italic: bool = False) -> Optional[tuple]:
    """
    从在线字体库下载字体到 downloads 目录，返回 (path, face_index) 或 None。

    支持新格式（CDN 索引）和旧格式（直接 URL）。
    新格式：从 onlineFonts.json 中根据字体名查候选 face，选最匹配 bold/italic 的，
            从 CDN hosts 依次尝试下载；下载后保存到 downloads 子目录（保留相对路径）。
    旧格式：直接用 entry["url"] 下载。
    """
    db = await _load_online_index()
    key = font_name.lower().strip().lstrip("@")
    entry = db.get(key)
    if not entry:
        # 前缀模糊匹配（兼容旧行为）
        for k, v in db.items():
            if k.startswith(key) or key.startswith(k):
                entry = v
                break
    if not entry:
        return None

    _FONTS_DOWNLOAD.mkdir(parents=True, exist_ok=True)

    # ── 旧格式 ────────────────────────────────────────────────────────────────
    if entry.get("_fmt") == "old":
        if not entry.get("url"):
            return None
        safe = re.sub(r"[^\w\-.]", "_", entry.get("name", font_name))
        for ext in (".ttf", ".otf", ".ttc"):
            dst = _FONTS_DOWNLOAD / f"{safe}{ext}"
            if dst.exists():
                logger.debug("[builtin] downloads 缓存命中: %s", dst.name)
                return str(dst), 0
        try:
            logger.info("[builtin] 下载字体（旧格式）: %s → %s", font_name, entry["url"])
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(entry["url"])
            if resp.status_code != 200:
                logger.warning("[builtin] 字体下载失败 HTTP %d: %s", resp.status_code, font_name)
                return None
            ct = resp.headers.get("content-type", "")
            url_lower = entry["url"].lower()
            ext = (".otf" if ("otf" in ct or url_lower.endswith(".otf")) else
                   ".ttc" if ("ttc" in ct or url_lower.endswith(".ttc")) else ".ttf")
            dst = _FONTS_DOWNLOAD / f"{safe}{ext}"
            dst.write_bytes(resp.content)
            logger.info("[builtin] 字体已保存: %s (%d KB)", dst.name, len(resp.content) // 1024)
            _invalidate_downloads_db()
            return str(dst), 0
        except Exception as e:
            logger.warning("[builtin] 字体下载异常: %s → %s", font_name, e)
            return None

    # ── 新格式（CDN 索引）────────────────────────────────────────────────────
    hosts: list = entry.get("_hosts", [])
    candidates: list = entry.get("_candidates", [])
    if not hosts or not candidates:
        return None

    best = _select_best_candidate(candidates, is_bold=is_bold, is_italic=is_italic)
    if not best:
        return None

    rel_path: str = best.get("path", "")
    face_idx: int = best.get("index", 0) or 0
    if not rel_path:
        return None

    # 检查本地缓存（按相对路径在 downloads 下保留完整目录结构）
    local_dst = _FONTS_DOWNLOAD / rel_path
    if local_dst.exists():
        logger.debug("[builtin] downloads 缓存命中（新格式）: %s", rel_path)
        return str(local_dst), face_idx

    # 依次尝试各 CDN host 下载
    local_dst.parent.mkdir(parents=True, exist_ok=True)
    for host in hosts:
        url = f"{host}{rel_path}"
        try:
            logger.info("[builtin] 下载字体（新格式）: %s → %s", font_name, url)
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                local_dst.write_bytes(resp.content)
                logger.info("[builtin] 字体已保存: %s (%d KB) face=%d",
                            rel_path, len(resp.content) // 1024, face_idx)
                _invalidate_downloads_db()
                return str(local_dst), face_idx
            logger.debug("[builtin] CDN 下载失败 HTTP %d: %s", resp.status_code, url)
        except Exception as e:
            logger.debug("[builtin] CDN 下载异常，尝试下一个: %s → %s", url, e)

    logger.warning("[builtin] 字体所有 CDN 均下载失败: %s", font_name)
    return None


# ═══════════════════════════════════════════════════════════
# Part 4: 字体子集化 + UUEncode + [Fonts] 段写入
# ═══════════════════════════════════════════════════════════

def _subset_font_sync(font_path: str, face_index: int, unicodes: set) -> Optional[bytes]:
    """fonttools 子集化（同步 CPU 密集，asyncio.to_thread 调用）"""
    try:
        from fontTools.ttLib import TTFont
        from fontTools.subset import Subsetter, Options
    except ImportError:
        logger.error("[builtin] fonttools 未安装")
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
    """UUEncode 编码字体（与 fontInAss 格式完全兼容）"""
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


def _extract_fonts_section(ass_text: str) -> tuple:
    """
    从 ASS 文本中分离出 [Fonts] 段，返回 (ass_without_fonts, existing_blocks)。

    existing_blocks: dict {filename_lower: raw_block_str}
      每个 block = "filename: xxx\n<uuencoded lines>\n`\n"
      key 是小写文件名（去扩展名），用于判断是否已内嵌。
    ass_without_fonts: 去掉 [Fonts] 段后的其余 ASS 内容。
    """
    # 提取 [Fonts] 段的原始文本
    m = re.search(r"\[Fonts\](.*?)(?=\n\[|\Z)", ass_text, flags=re.DOTALL)
    if not m:
        return ass_text, {}

    fonts_body = m.group(1)
    ass_without = (ass_text[:m.start()] + ass_text[m.end():]).rstrip()

    # 按 "filename:" 行切分，每段是一个字体块
    blocks: dict = {}
    current_name: str = ""
    current_lines: list = []

    for line in fonts_body.splitlines():
        s = line.strip()
        # fontInAss 生成的字体块使用 "fontname:" 前缀
        # 标准 ASS 规范使用 "filename:" 前缀，两种都要识别
        s_lower = s.lower()
        if s_lower.startswith("filename:"):
            key_len = 9
        elif s_lower.startswith("fontname:"):
            key_len = 9
        else:
            key_len = 0

        if key_len:
            # 保存上一个块
            if current_name and current_lines:
                blocks[current_name] = "\n".join(current_lines) + "\n"
            raw_name = s[key_len:].strip()
            name_lower = raw_name.lower()
            for ext in (".ttf", ".otf", ".ttc", ".otc"):
                if name_lower.endswith(ext):
                    name_lower = name_lower[:-len(ext)]
                    break
            current_name = name_lower
            current_lines = [line]
        elif current_name:
            current_lines.append(line)

    # 最后一个块
    if current_name and current_lines:
        blocks[current_name] = "\n".join(current_lines) + "\n"

    return ass_without, blocks


def _insert_fonts_section(ass_text: str, font_entries: dict) -> str:
    """
    将子集化字体写入 ASS [Fonts] 段。

    混合字幕处理（部分已内嵌、部分需子集化）：
      - 保留原 [Fonts] 段中不在 font_entries 里的已内嵌字体块
      - 用新子集化结果替换/追加 font_entries 中的字体块
    这样已内嵌字体（随机名如 RM8KN26Q）不会因为写入新字体而丢失。
    """
    ass_without, existing_blocks = _extract_fonts_section(ass_text)

    # 新 font_entries 的 key 集合（小写字体名，去扩展名）
    new_keys: set = set()
    for key in font_entries:
        fname = key.rsplit("^", 1)[0] if "^" in key else key
        new_keys.add(fname.lower())

    # 保留旧块中不被新内容覆盖的已内嵌字体
    preserved = "".join(
        block for name, block in existing_blocks.items()
        if name not in new_keys
    )

    section = "[Fonts]\n" + preserved + "".join(font_entries.values())
    return ass_without + "\n\n" + section


# ═══════════════════════════════════════════════════════════
# Part 5: 主入口（含 reMap：同字体文件字符集合并，只子集化一次）
# ═══════════════════════════════════════════════════════════

async def _process_ass_content(ass_text: str, raw_bytes: bytes) -> tuple:
    """
    ASS 内容子集化核心。
    返回 (result_bytes, missing_fonts, content_type)

    对齐 fontInAss subsetter.py 的处理逻辑：
      1. [Fonts] 段已有内容 → 直接透传（字体已内嵌，无需重复处理）
      2. [Fonts] 段存在但无内容 → 清除空段再处理
      3. 无 [Fonts] 段 → 正常子集化流程
    reMap 优化：同一字体文件被多个 key 引用时合并字符集，只子集化一次。
    """
    # ── 第一步：检查 [Fonts] 段状态（对齐 fontInAss check_section 逻辑）────────
    # fontInAss 原话：status==1（有内容）→ "已有内嵌字体"，直接返回原始内容
    # 不解析字体名、不查找、不子集化，因为字体数据已经在里面了
    ass_without_fonts, existing_blocks = _extract_fonts_section(ass_text)
    if existing_blocks:
        # [Fonts] 段有实际字体内容 → 直接透传
        logger.info("[builtin] 字幕已含内嵌字体（%s），直接透传",
                    ", ".join(sorted(existing_blocks.keys())))
        return raw_bytes, [], "text/x-ssa; charset=utf-8"

    # existing_blocks 为空但 [Fonts] 段可能存在（空段）→ 用去掉空段的文本处理
    # ass_without_fonts 已移除 [Fonts] 段，后续写入时重新生成
    # 使用 ass_without_fonts 进行解析和最终写入，避免空 [Fonts] 段干扰
    font_chars = analyse_ass(ass_without_fonts)
    if not font_chars:
        logger.info("[builtin] ASS 无字体信息，直接返回原始内容")
        return raw_bytes, [], "text/x-ssa; charset=utf-8"

    logger.info("[builtin] ASS 解析: %d 个字体 key: %s",
                len(font_chars),
                ", ".join(f"{k}({len(v)}字符)" for k, v in font_chars.items()))

    font_resolved: dict = {}
    missing: list = []

    # ── 并发查找所有字体：DB 与在线下载并行，本地优先 ──────────────────────
    async def _resolve_one(key: str) -> tuple:
        """
        返回 (key, loc_or_None)。
        策略：DB 查询与在线下载同时发起（asyncio.gather），
        DB 命中则优先使用本地结果；DB 未命中则用在线下载结果。
        """
        fname, subfamily = (key.rsplit("^", 1) if "^" in key
                            else (key, _VARIANT_REGULAR))
        is_bold   = "Bold"   in subfamily
        is_italic = "Italic" in subfamily

        async def _db_lookup() -> Optional[tuple]:
            try:
                from src.services.font_index_service import find_font_in_db
                return await find_font_in_db(fname, is_bold=is_bold, is_italic=is_italic)
            except Exception:
                return None

        async def _online_lookup() -> Optional[tuple]:
            return await download_font(fname, is_bold=is_bold, is_italic=is_italic)

        # DB 和在线同时查找
        db_loc, online_loc = await asyncio.gather(_db_lookup(), _online_lookup())

        # 本地优先：DB 命中则忽略在线结果
        loc = db_loc or online_loc
        return key, loc

    resolve_results = await asyncio.gather(*[_resolve_one(k) for k in font_chars])

    for key, loc in resolve_results:
        if loc:
            font_resolved[key] = loc
        else:
            missing.append(key)

    # 一条日志汇总查找结果
    found_summary = [f"✅{k}({font_resolved[k][0].rsplit('/', 1)[-1]})" for k in font_resolved]
    miss_summary  = [f"❌{k}" for k in missing]
    logger.info("[builtin] 字体查找: %s", "  ".join(found_summary + miss_summary) or "无")

    if not font_resolved:
        logger.warning("[builtin] 所有字体均缺失，返回原始字幕")
        return raw_bytes, missing, "text/x-ssa; charset=utf-8"

    # ── reMap：按 (path, face_index) 合并字符集 ──────────────────────────────
    re_map: "dict[tuple, set]" = defaultdict(set)
    file_to_keys: "dict[tuple, list]" = defaultdict(list)
    for key, loc in font_resolved.items():
        fk = (loc[0], loc[1])
        re_map[fk] |= font_chars[key]
        file_to_keys[fk].append(key)

    # ── 并行子集化 ────────────────────────────────────────────────────────────
    async def _do_subset(fk: tuple) -> tuple:
        path, idx = fk
        orig_size = os.path.getsize(path) if os.path.exists(path) else 0
        result = await asyncio.to_thread(_subset_font_sync, path, idx, re_map[fk])
        return fk, result, orig_size

    subset_results = await asyncio.gather(*[_do_subset(fk) for fk in re_map])

    # ── UUEncode + 写入 [Fonts] ───────────────────────────────────────────────
    font_entries: dict = {}
    subset_ok: list = []
    subset_fail: list = []
    for fk, subset_bytes, orig_size in subset_results:
        path, idx = fk
        keys = file_to_keys[fk]
        fname_short = path.rsplit("/", 1)[-1]
        if not subset_bytes:
            missing.extend(keys)
            subset_fail.append(f"❌{fname_short}#{idx}")
            continue
        ratio = len(subset_bytes) / orig_size * 100 if orig_size else 0
        subset_ok.append(f"✅{fname_short}#{idx}({orig_size}→{len(subset_bytes)}B,{ratio:.0f}%)")
        for key in keys:
            fname = key.rsplit("^", 1)[0] if "^" in key else key
            font_entries[key] = _uuencode_font(subset_bytes, fname)

    if not font_entries:
        logger.warning("[builtin] 子集化全部失败，返回原始字幕  缺失=%s",
                       ", ".join(missing))
        return raw_bytes, missing, "text/x-ssa; charset=utf-8"

    ass_out = _insert_fonts_section(ass_without_fonts, font_entries)
    out_bytes = ass_out.encode("utf-8")
    logger.info(
        "[builtin] ✅ 子集化完成: %d→%d bytes  成功=%s%s",
        len(raw_bytes), len(out_bytes),
        " ".join(subset_ok),
        ("  失败=" + " ".join(subset_fail)) if subset_fail else "",
    )
    return out_bytes, missing, "text/x-ssa; charset=utf-8"


async def process_subtitle_builtin(raw_bytes: bytes) -> tuple:
    """
    内置字幕子集化主入口，支持 ASS / SRT / VTT / 其他格式。
    Returns: (processed_bytes, missing_fonts, content_type)
    """
    t0 = time.monotonic()

    cache_key = hashlib.md5(raw_bytes).hexdigest()
    now = t0
    if cache_key in _result_cache:
        cached_bytes, expire_ts = _result_cache[cache_key]
        if now < expire_ts:
            logger.debug("[builtin] 命中结果缓存: key=%s %d bytes", cache_key[:8], len(cached_bytes))
            return cached_bytes, [], "text/x-ssa; charset=utf-8"
        del _result_cache[cache_key]

    fmt = _detect_format(raw_bytes)

    if fmt == "vtt":
        return raw_bytes, [], "text/vtt; charset=utf-8"
    if fmt == "unknown":
        return raw_bytes, [], "text/plain; charset=utf-8"

    enc_used = "utf-8"
    for enc in ("utf-8-sig", "gbk", "latin-1"):
        try:
            text = raw_bytes.decode(enc)
            enc_used = enc
            break
        except Exception:
            continue
    else:
        text = raw_bytes.decode("utf-8", errors="replace")

    if fmt == "srt":
        text = srt_to_ass(text)

    logger.info("[builtin] 开始子集化: fmt=%s enc=%s size=%d bytes", fmt, enc_used, len(raw_bytes))
    result_bytes, missing, ct = await _process_ass_content(text, raw_bytes)

    elapsed = time.monotonic() - t0
    if missing:
        logger.warning("[builtin] 子集化完成: %d→%d bytes 耗时=%.1fs 缺失字体=%s",
                       len(raw_bytes), len(result_bytes), elapsed, ", ".join(missing))
    else:
        logger.info("[builtin] 子集化完成: %d→%d bytes 耗时=%.1fs",
                    len(raw_bytes), len(result_bytes), elapsed)

    _result_cache[cache_key] = (result_bytes, now + _RESULT_CACHE_TTL)
    if len(_result_cache) > _RESULT_CACHE_MAX:
        _result_cache.popitem(last=False)

    return result_bytes, missing, ct


async def process_ass_builtin(ass_bytes: bytes) -> tuple:
    """向后兼容旧接口名，委托给 process_subtitle_builtin。"""
    result_bytes, missing, _ = await process_subtitle_builtin(ass_bytes)
    return result_bytes, missing
