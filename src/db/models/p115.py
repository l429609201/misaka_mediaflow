# app/db/models/p115.py
# 表 9:  p115fscache — 115 目录树缓存
# 表 10: p115mediainfo — 115 媒体信息指纹库
# 表 11: p115organizerecord — 115 文件整理记录

from sqlalchemy import Column, BigInteger, String, Text

from src.db.base import Base
from src.db import get_id_column
from src.core.timezone import tm


class P115FsCache(Base):
    """115 目录树缓存 — 文件系统本地镜像"""
    __tablename__ = "p115fscache"

    id          = get_id_column()
    file_id     = Column(String(255), nullable=False, unique=True, comment="115的cid(目录)或fid(文件)")
    parent_id   = Column(String(255), nullable=False, index=True, comment="父目录ID")
    name        = Column(Text, nullable=False, comment="文件/文件夹名称")
    local_path  = Column(Text, default="", comment="本地映射路径")
    sha1        = Column(String(255), default="", index=True, comment="文件SHA1哈希")
    pick_code   = Column(String(255), default="", index=True, comment="115提取码pickcode")
    ed2k        = Column(Text, default="", comment="ed2k哈希")
    file_size   = Column(BigInteger, default=0, comment="文件大小(字节)")
    is_dir      = Column(BigInteger, default=0, comment="是否目录: 1/0")
    mtime       = Column(Text, default="", comment="115文件修改时间")
    ctime       = Column(Text, default="", comment="115文件创建时间")
    updated_at  = Column(Text, default=tm.now, comment="本地同步时间")


class P115MediaInfo(Base):
    """115 媒体信息指纹库 — SHA1 → 媒体规格缓存"""
    __tablename__ = "p115mediainfo"

    id              = get_id_column()
    sha1            = Column(String(255), nullable=False, unique=True, comment="文件SHA1(唯一标识)")
    mediainfo_json  = Column(Text, default="{}", comment="完整媒体信息JSON(编码/分辨率/音轨)")
    hit_count       = Column(BigInteger, default=0, comment="缓存命中次数")
    created_at      = Column(Text, default=tm.now, comment="创建时间")


class P115OrganizeRecord(Base):
    """115 文件整理记录 — OpenAPI 整理操作日志"""
    __tablename__ = "p115organizerecord"

    id              = get_id_column()
    file_id         = Column(String(255), nullable=False, unique=True, comment="115原始文件ID")
    pick_code       = Column(String(255), default="", index=True, comment="提取码")
    original_name   = Column(Text, default="", comment="原始文件名")
    renamed_name    = Column(Text, default="", comment="整理后文件名")
    status          = Column(String(255), default="pending", index=True, comment="状态: success/unrecognized/failed")
    tmdb_id         = Column(Text, default="", comment="关联TMDB ID")
    media_type      = Column(Text, default="", comment="媒体类型: movie/tv")
    target_cid      = Column(Text, default="", comment="目标分类目录CID")
    category_name   = Column(Text, default="", comment="分类名称")
    processed_at    = Column(Text, default=tm.now, comment="处理时间")

