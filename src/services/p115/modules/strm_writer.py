# src/services/p115/modules/strm_writer.py
# STRM 文件写入模块
# 负责路径计算、URL 渲染、.strm 文件写入，与业务调度层解耦。

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from src.db import get_async_session_local
from src.db.models.system import SystemConfig

logger = logging.getLogger(__name__)

_STRM_URL_TEMPLATE_KEY = "strm_url_template"


async def get_url_template() -> str:
    """从数据库读取 STRM URL 模板。
    模板以 json.dumps 形式存储（与 /api/v1/strm/url-template 接口一致），
    需要 json.loads 还原为纯字符串。
    """
    import json as _json
    try:
        async with get_async_session_local() as db:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.key == _STRM_URL_TEMPLATE_KEY)
            )
            cfg = result.scalars().first()
            if cfg and cfg.value and cfg.value.strip():
                try:
                    return _json.loads(cfg.value)
                except Exception:
                    # 兼容旧数据（未 JSON 序列化的纯文本）
                    return cfg.value.strip()
    except Exception as e:
        logger.debug("读取 STRM URL 模板失败: %s", e)
    return ""


def calc_rel_path(item_full_path: str, cloud_path: str) -> Path:
    """
    计算文件相对于 cloud_path 根目录的相对路径（不含文件名）。
    例：cloud_path=/影音, item_full_path=/影音/电影/xxx.mkv → rel=电影
    """
    cloud_root = "/" + cloud_path.strip("/")
    full = "/" + item_full_path.strip("/")
    try:
        rel_str = Path(full).parent.relative_to(cloud_root)
    except ValueError:
        rel_str = Path(".")
    return Path(rel_str)


def get_strm_filename(filename: str) -> str:
    """
    计算 .strm 文件名。
    对齐 p115strmhelper StrmGenerater.get_strm_filename：
      .iso 文件保留扩展名 → stem.iso.strm；其他文件 → stem.strm
    """
    suffix = Path(filename).suffix.lower()
    stem   = Path(filename).stem
    return f"{stem}.iso.strm" if suffix == ".iso" else f"{stem}.strm"


def render_strm_url(
    url_tmpl: str,
    link_host: str,
    pick_code: str,
    filename: str,
    cloud_path: str,
    sha1: str = "",
) -> str:
    """
    渲染 STRM 文件内容（URL）。
    支持 Jinja2 风格模板语法（对齐 p115strmhelper StrmUrlTemplateResolver）：
      {{ base_url }}               → link_host
      {{ pickcode }}               → pick_code
      {{ file_name }}              → 文件名（含扩展名）
      {{ file_path }}              → 云盘完整路径
      {{ sha1 }}                   → 文件 SHA1
      {{ file_name | urlencode }}  → URL 编码（不保留斜杠）
      {{ file_path | urlencode }}  → URL 编码（不保留斜杠）
      {{ file_path | path_encode }}→ URL 编码（保留斜杠）
      {{ file_name | upper }}      → 转大写
      {{ file_name | lower }}      → 转小写
      {% if file_name %}…{% endif %}→ 条件块
    fallback：{host}/api/v1/p115/play/redirect_url/{pickcode}/{filename}
    """
    import re
    from urllib.parse import quote as _url_quote

    encoded_name = _url_quote(filename, safe="")
    default_url  = f"{link_host}/api/v1/p115/play/redirect_url/{pick_code}/{encoded_name}"

    if not url_tmpl or not url_tmpl.strip():
        return default_url

    try:
        variables = {
            "base_url":  link_host,
            "pickcode":  pick_code,
            "file_name": filename,
            "file_path": cloud_path,
            "sha1":      sha1,
        }

        def _replace(m: re.Match) -> str:
            expr = m.group(1).strip()
            if "|" in expr:
                parts    = [p.strip() for p in expr.split("|", 1)]
                var_name = parts[0]
                filt     = parts[1]
                val      = str(variables.get(var_name, ""))
                if filt == "urlencode":
                    return _url_quote(val, safe="")
                if filt == "path_encode":
                    return _url_quote(val, safe="/")
                if filt == "upper":
                    return val.upper()
                if filt == "lower":
                    return val.lower()
                return val
            return str(variables.get(expr, ""))

        # 先处理条件块 {% if var %}…{% endif %}
        def _resolve_if(m: re.Match) -> str:
            var_name = m.group(1).strip()
            body     = m.group(2)
            return body if variables.get(var_name) else ""

        rendered = re.sub(
            r"\{%-?\s*if\s+(\w+)\s*-?%\}(.*?)\{%-?\s*endif\s*-?%\}",
            _resolve_if, url_tmpl, flags=re.DOTALL,
        )
        rendered = re.sub(r"\{\{\s*(.*?)\s*\}\}", _replace, rendered)
        return rendered.strip()

    except Exception as e:
        logger.warning("STRM URL 模板渲染失败: %s，使用默认格式", e)
        return default_url


def write_strm(
    strm_root: Path,
    rel: Path,
    filename: str,
    strm_url: str,
    overwrite_mode: str = "skip",
) -> str:
    """
    写 .strm 文件到本地。
    overwrite_mode:
      "skip"      → 文件已存在时跳过（对齐 p115strmhelper overwrite_mode=never）
      "overwrite" → 文件已存在时强制覆盖（对齐 p115strmhelper overwrite_mode=always）
    返回值：
      "created"  → 新建或覆盖写入
      "skipped"  → 文件已存在且跳过
      "error"    → 写入失败
    """
    try:
        strm_dir = strm_root / rel
        strm_dir.mkdir(parents=True, exist_ok=True)
        strm_name = get_strm_filename(filename)
        strm_file = strm_dir / strm_name
        strm_content = strm_url

        if strm_file.exists():
            existing = strm_file.read_text(encoding="utf-8").strip()
            if existing == strm_content.strip():
                logger.debug("STRM 文件已存在且内容相同，跳过: %s", strm_file)
                return "skipped"
            if overwrite_mode == "skip":
                logger.debug("STRM 文件已存在，覆盖模式 skip，跳过: %s", strm_file)
                return "skipped"
            logger.debug("STRM 文件内容变更，覆盖: %s", strm_file)
        else:
            logger.debug("新建 STRM 文件: %s → %s", strm_file, strm_content)

        strm_file.write_text(strm_content, encoding="utf-8")
        logger.info("【STRM写入】生成 STRM 文件成功: %s", str(strm_file))
        return "created"
    except Exception as e:
        logger.error("【STRM写入】写入 STRM 文件失败: %s  %s", filename, e)
        return "error"

