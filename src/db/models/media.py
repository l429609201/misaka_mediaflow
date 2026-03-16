# app/db/models/media.py
# 表 3: mediaitem — 媒体条目

from sqlalchemy import Column, BigInteger, String, Text

from src.db.base import Base
from src.db import get_id_column
from src.core.timezone import tm


class MediaItem(Base):
    """媒体条目 — Emby/Jellyfin 媒体库同步"""
    __tablename__ = "mediaitem"

    id              = get_id_column()
    item_id         = Column(String(255), nullable=False, unique=True, comment="Emby/Jellyfin媒体ID")
    title           = Column(Text, nullable=False, comment="标题")
    item_type       = Column(String(255), nullable=False, index=True, comment="类型: Movie/Series/Season/Episode")
    year            = Column(BigInteger, default=0, comment="年份")
    parent_id       = Column(String(255), default="", index=True, comment="父级ID")
    season_num      = Column(BigInteger, default=0, comment="季号")
    episode_num     = Column(BigInteger, default=0, comment="集号")
    library_id      = Column(String(255), default="", index=True, comment="媒体库ID")
    file_path       = Column(Text, default="", comment="文件路径")
    file_size       = Column(BigInteger, default=0, comment="文件大小(字节)")
    container       = Column(Text, default="", comment="容器格式: mkv/mp4")
    media_source_id = Column(Text, default="", comment="MediaSourceId")
    tmdb_id         = Column(BigInteger, default=0, index=True, comment="TMDB ID")
    imdb_id         = Column(Text, default="", comment="IMDB ID")
    # ⭐ 115 网盘专属字段
    file_sha1       = Column(String(255), default="", index=True, comment="115文件SHA1")
    pick_code       = Column(String(255), default="", index=True, comment="115提取码pickcode")
    file_115_id     = Column(Text, default="", comment="115文件fid")
    ed2k            = Column(Text, default="", comment="115 ed2k哈希")
    mtime_115       = Column(Text, default="", comment="115文件修改时间")
    ctime_115       = Column(Text, default="", comment="115文件创建时间")
    # 媒体规格信息（参考 Lens MediaItem）
    video_codec     = Column(Text, default="", comment="视频编码: H.264/HEVC/AV1")
    video_range     = Column(Text, default="", comment="视频范围: SDR/HDR/DV")
    audio_codec     = Column(Text, default="", comment="音频编码: AAC/DTS/TrueHD")
    display_title   = Column(Text, default="", comment="媒体流显示标题")
    raw_data        = Column(Text, default="{}", comment="完整API响应JSON")
    synced_at       = Column(Text, default=tm.now, comment="同步时间")

