# src/db/models/metadata.py
# 媒体元数据完整表结构 — Series/Season/Episode/Person/Cast
#
# 设计原则:
#   - 与 MediaItem 分离: MediaItem 给 STRM/代理用，这套表给刮削/缺集/演员用
#   - 支持从 Emby 同步 + 从 TMDB 刮削 + 推回 Emby
#   - 参考 emby-toolkit 的 person_metadata 设计

from sqlalchemy import Column, BigInteger, String, Text, Integer, Float

from src.db.base import Base
from src.db import get_id_column
from src.core.timezone import tm


class MetaSeries(Base):
    """剧集/电影 主表"""
    __tablename__ = "meta_series"

    id              = get_id_column()
    emby_id         = Column(String(255), default="", unique=True, index=True, comment="Emby Item ID")
    title           = Column(String(512), default="", comment="标题（中文优先）")
    original_title  = Column(String(512), default="", comment="原始标题")
    sort_title      = Column(String(512), default="", comment="排序标题")
    media_type      = Column(String(32), default="Series", index=True, comment="Movie/Series")
    year            = Column(Integer, default=0, comment="年份")
    overview        = Column(Text, default="", comment="概述/简介")
    poster_path     = Column(Text, default="", comment="海报路径(TMDB相对路径)")
    backdrop_path   = Column(Text, default="", comment="背景图路径")
    tmdb_id         = Column(BigInteger, default=0, index=True, comment="TMDB ID")
    imdb_id         = Column(String(64), default="", index=True, comment="IMDB ID")
    tvdb_id         = Column(BigInteger, default=0, comment="TVDB ID")
    douban_id       = Column(String(64), default="", comment="豆瓣 ID")
    genres          = Column(Text, default="", comment="类型 JSON: ['动作','科幻']")
    status          = Column(String(32), default="", comment="状态: Ended/Returning Series/Released")
    vote_average    = Column(Float, default=0, comment="评分")
    vote_count      = Column(Integer, default=0, comment="评分人数")
    total_seasons   = Column(Integer, default=0, comment="TMDB 总季数(不含S0)")
    total_episodes  = Column(Integer, default=0, comment="TMDB 总集数")
    emby_episodes   = Column(Integer, default=0, comment="Emby 已有集数")
    origin_country  = Column(String(64), default="", comment="产地 如 JP,US")
    original_lang   = Column(String(16), default="", comment="原始语言 如 ja,en")
    library_id      = Column(String(255), default="", comment="Emby 媒体库 ID")
    scraped         = Column(Integer, default=0, comment="是否已刮削 0/1")
    synced_at       = Column(Text, default=tm.now, comment="Emby 同步时间")
    scraped_at      = Column(Text, default="", comment="TMDB 刮削时间")

    def to_dict(self):
        return {c.name: getattr(self, c.name, None) for c in self.__table__.columns}


class MetaSeason(Base):
    """季"""
    __tablename__ = "meta_season"

    id              = get_id_column()
    series_id       = Column(BigInteger, default=0, index=True, comment="关联 meta_series.id")
    emby_id         = Column(String(255), default="", index=True, comment="Emby Season ID")
    season_number   = Column(Integer, default=0, comment="季号")
    title           = Column(String(512), default="", comment="季标题")
    overview        = Column(Text, default="", comment="季概述")
    poster_path     = Column(Text, default="", comment="季海报路径")
    tmdb_episodes   = Column(Integer, default=0, comment="TMDB 该季总集数")
    emby_episodes   = Column(Integer, default=0, comment="Emby 该季已有集数")
    air_date        = Column(String(32), default="", comment="首播日期")
    synced_at       = Column(Text, default=tm.now, comment="同步时间")

    def to_dict(self):
        return {c.name: getattr(self, c.name, None) for c in self.__table__.columns}


class MetaEpisode(Base):
    """集"""
    __tablename__ = "meta_episode"

    id              = get_id_column()
    series_id       = Column(BigInteger, default=0, index=True, comment="关联 meta_series.id")
    season_id       = Column(BigInteger, default=0, index=True, comment="关联 meta_season.id")
    emby_id         = Column(String(255), default="", index=True, comment="Emby Episode ID")
    season_number   = Column(Integer, default=0, comment="季号")
    episode_number  = Column(Integer, default=0, comment="集号")
    title           = Column(String(512), default="", comment="集标题")
    overview        = Column(Text, default="", comment="集概述")
    air_date        = Column(String(32), default="", comment="播出日期")
    still_path      = Column(Text, default="", comment="剧照路径")
    file_path       = Column(Text, default="", comment="文件路径")
    pick_code       = Column(String(255), default="", comment="115 pickcode")
    runtime         = Column(Integer, default=0, comment="时长(分钟)")
    source          = Column(String(16), default="emby", comment="来源: emby/tmdb")
    synced_at       = Column(Text, default=tm.now, comment="同步时间")

    def to_dict(self):
        return {c.name: getattr(self, c.name, None) for c in self.__table__.columns}


class MetaPerson(Base):
    """演员元数据（参考 emby-toolkit person_metadata）"""
    __tablename__ = "meta_person"

    id              = get_id_column()
    emby_id         = Column(String(255), default="", index=True, comment="Emby Person ID")
    tmdb_id         = Column(BigInteger, default=0, index=True, comment="TMDB Person ID")
    imdb_id         = Column(String(64), default="", index=True, comment="IMDB ID")
    douban_id       = Column(String(64), default="", comment="豆瓣 Celebrity ID")
    name_cn         = Column(String(255), default="", comment="中文名")
    name_en         = Column(String(255), default="", comment="英文名")
    name_original   = Column(String(255), default="", comment="原始名")
    gender          = Column(Integer, default=0, comment="性别 0=未知 1=女 2=男")
    profile_path    = Column(Text, default="", comment="头像路径(TMDB相对路径)")
    biography       = Column(Text, default="", comment="简介")
    birthday        = Column(String(32), default="", comment="生日")
    place_of_birth  = Column(String(255), default="", comment="出生地")
    popularity      = Column(Float, default=0, comment="TMDB 人气值")
    adult           = Column(Integer, default=0, comment="是否成人 0/1")
    synced_at       = Column(Text, default=tm.now, comment="同步时间")

    def to_dict(self):
        return {c.name: getattr(self, c.name, None) for c in self.__table__.columns}


class MetaCast(Base):
    """媒体-演员关联表"""
    __tablename__ = "meta_cast"

    id              = get_id_column()
    series_id       = Column(BigInteger, default=0, index=True, comment="关联 meta_series.id")
    person_id       = Column(BigInteger, default=0, index=True, comment="关联 meta_person.id")
    character       = Column(String(512), default="", comment="角色名")
    cast_type       = Column(String(32), default="Actor", comment="Actor/Director/Writer/GuestStar")
    cast_order      = Column(Integer, default=999, comment="排序")
    synced_at       = Column(Text, default=tm.now, comment="同步时间")

    def to_dict(self):
        return {c.name: getattr(self, c.name, None) for c in self.__table__.columns}
