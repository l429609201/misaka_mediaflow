# src/db/models/gaps.py
# 缺集管理 — Emby 剧集同步缓存表

from sqlalchemy import Column, BigInteger, String, Text, Integer

from src.db.base import Base
from src.db import get_id_column
from src.core.timezone import tm


class GapsSeries(Base):
    """Emby 剧集同步数据（缺集比对用）"""
    __tablename__ = "gaps_series"

    id          = get_id_column()
    series_id   = Column(String(255), nullable=False, index=True, unique=True, comment="Emby Series ID")
    series_name = Column(String(512), default="", comment="剧集名称")
    tmdb_id     = Column(BigInteger, default=0, index=True, comment="TMDB ID")
    imdb_id     = Column(String(64), default="", comment="IMDB ID")
    poster_url  = Column(Text, default="", comment="海报URL")
    seasons_json = Column(Text, default="{}", comment="已有集数 JSON: {season_num: [ep1,ep2,...]}")
    total_episodes = Column(Integer, default=0, comment="Emby 中的总集数")
    synced_at   = Column(Text, default=tm.now, comment="同步时间")

    def to_dict(self):
        return {
            "id":             self.id,
            "series_id":      self.series_id,
            "series_name":    self.series_name,
            "tmdb_id":        self.tmdb_id,
            "imdb_id":        self.imdb_id,
            "poster_url":     self.poster_url,
            "seasons_json":   self.seasons_json,
            "total_episodes": self.total_episodes,
            "synced_at":      self.synced_at,
        }
