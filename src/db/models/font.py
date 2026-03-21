# src/db/models/font.py
# 字体索引持久化模型（参考 fontInAss fontManager.py 三表设计）
#
# 表结构与级联关系：
#   FontFile  — 字体文件记录（path 唯一）
#     └─(1:N)─ FontFace  — 字体 face 元数据（TTC 多 face 支持）
#                └─(1:N)─ FontName  — 字体名称索引（查找入口）
#
#   SubtitleFile — 外部字幕登记表，软关联 mediaitem.item_id
#
# 级联删除：
#   删除 FontFile → CASCADE 删 FontFace → CASCADE 删 FontName
#   磁盘字体文件被删除时，只需 DELETE FontFile，其余自动清理
#
# 与 fontInAss 的差异：
#   - 使用项目主数据库（MySQL/PostgreSQL）而非独立 SQLite
#   - file_hash 用 MD5 检测文件内容变化（fontInAss 用 size）
#   - 增加 SubtitleFile 表关联媒体条目

from sqlalchemy import Column, BigInteger, String, Text, Integer, ForeignKey
from src.db.base import Base
from src.db import get_id_column
from src.core.timezone import tm


class FontFile(Base):
    """
    字体文件表 — 记录磁盘上每一个字体文件。
    path 作为业务唯一键；file_hash 用于检测文件内容是否变化。
    """
    __tablename__ = "font_file"

    id          = get_id_column()
    path        = Column(Text, nullable=False, comment="字体文件绝对路径")
    path_hash   = Column(String(64), nullable=False, unique=True, index=True,
                         comment="路径的 MD5（作为唯一键，避免 Text 列不能建 unique）")
    file_size   = Column(BigInteger, default=0, comment="文件大小(字节)")
    file_hash   = Column(String(64), default="", index=True,
                         comment="文件内容 MD5，变化时触发重新扫描")
    scanned_at  = Column(Text, default=tm.now, comment="最近扫描时间")


class FontFace(Base):
    """
    字体 Face 元数据表 — 对应 fontInAss 的 FontInfo。
    一个字体文件（FontFile）可含多个 face（TTC/OTC 集合）。
    删除父 FontFile 时级联删除。
    """
    __tablename__ = "font_face"

    id               = get_id_column()
    file_id          = Column(BigInteger, ForeignKey("font_file.id", ondelete="CASCADE"),
                              nullable=False, index=True, comment="关联字体文件ID")
    face_index       = Column(Integer, default=0, comment="face 序号(TTC 集合用，TTF 固定为 0)")
    family_names     = Column(Text, default="[]", comment="Family 名列表 JSON (nameID 1)")
    full_names       = Column(Text, default="[]", comment="Full 名列表 JSON (nameID 4)")
    postscript_names = Column(Text, default="[]", comment="PostScript 名列表 JSON (nameID 6)")
    weight           = Column(Integer, default=400, comment="字重(100-900)，400=Regular，700=Bold")
    is_bold          = Column(Integer, default=0, comment="是否粗体: 1/0")
    is_italic        = Column(Integer, default=0, comment="是否斜体: 1/0")
    scanned_at       = Column(Text, default=tm.now, comment="扫描时间")


class FontName(Base):
    """
    字体名称索引表 — 对应 fontInAss 的 FontName(name 表)。
    每个 FontFace 的 familyName/fullName/postscriptName 均展开为独立行，
    以字体名为索引实现 O(log n) 查找。
    删除父 FontFace 时级联删除。
    """
    __tablename__ = "font_name"

    id       = get_id_column()
    name     = Column(String(512), nullable=False, index=True, comment="字体名称(小写存储，查找时也小写)")
    face_id  = Column(BigInteger, ForeignKey("font_face.id", ondelete="CASCADE"),
                      nullable=False, index=True, comment="关联 FontFace ID")


class SubtitleFile(Base):
    """
    外部字幕登记表 — 记录用户放入的外部字幕文件。
    软关联 mediaitem.item_id（不建外键，Emby item_id 可能不在本库）。
    font_keys 存储解析出的字体名列表，供子集化时快速定位所需字体。
    """
    __tablename__ = "subtitle_file"

    id          = get_id_column()
    item_id     = Column(String(255), default="", index=True,
                         comment="关联 Emby/Jellyfin 媒体 ID（软关联）")
    file_path   = Column(Text, nullable=False, comment="字幕文件绝对路径")
    path_hash   = Column(String(64), nullable=False, unique=True, index=True,
                         comment="路径 MD5（唯一键）")
    file_hash   = Column(String(64), default="", comment="文件内容 MD5，变化时重新解析")
    file_size   = Column(BigInteger, default=0, comment="文件大小(字节)")
    font_keys   = Column(Text, default="[]",
                         comment="解析出的字体 key 列表 JSON，如 [\"黑体^Bold\",\"Arial^Regular\"]")
    scanned_at  = Column(Text, default=tm.now, comment="最近扫描/解析时间")

