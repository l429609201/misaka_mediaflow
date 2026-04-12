# src/services/calendar_service.py
# 追剧日历服务 — TMDB 本周排期 + DB 中已同步的库交叉标记

import logging
from datetime import datetime

from sqlalchemy import select

from src.db import get_async_session_local
from src.db.models.metadata import MetaSeries

logger = logging.getLogger(__name__)


class CalendarService:
    """追剧日历：获取今日热播剧集，标记库中已有/缺失（从 DB 读取，不实时拉 Emby）"""

    async def _get_owned_tmdb_ids(self) -> set:
        """从 meta_series 表读取已同步的 TMDB ID 集合"""
        async with get_async_session_local() as db:
            rows = (await db.execute(
                select(MetaSeries.tmdb_id).where(MetaSeries.tmdb_id > 0)
            )).scalars().all()
        return {str(tid) for tid in rows}

    async def get_airing_today(self) -> dict:
        """获取今日正在播出的剧集"""
        from src.services.metadata_service import metadata_service

        tmdb = await metadata_service.get_provider("tmdb")
        if not tmdb:
            return {"error": "TMDB 未配置", "shows": []}

        # 从 DB 读取已同步的 TMDB ID（不实时拉 Emby）
        owned_tmdb_ids = await self._get_owned_tmdb_ids()

        shows = []
        try:
            for page in range(1, 4):
                data = await tmdb._get("/tv/airing_today", params={"page": page})
                results = data.get("results", [])
                if not results:
                    break
                for item in results:
                    tmdb_id = str(item.get("id", ""))
                    shows.append({
                        "tmdb_id": tmdb_id,
                        "name": item.get("name", ""),
                        "original_name": item.get("original_name", ""),
                        "overview": (item.get("overview") or "")[:120],
                        "poster_url": f"https://image.tmdb.org/t/p/w200{item['poster_path']}" if item.get("poster_path") else "",
                        "backdrop_url": f"https://image.tmdb.org/t/p/w500{item['backdrop_path']}" if item.get("backdrop_path") else "",
                        "vote_average": item.get("vote_average", 0),
                        "origin_country": item.get("origin_country", []),
                        "first_air_date": item.get("first_air_date", ""),
                        "in_library": tmdb_id in owned_tmdb_ids,
                    })
        except Exception as e:
            logger.error("[Calendar] TMDB 查询失败: %s", e)

        shows.sort(key=lambda s: (not s["in_library"], -s["vote_average"]))
        return {
            "date": datetime.utcnow().date().isoformat(),
            "total": len(shows),
            "in_library": sum(1 for s in shows if s["in_library"]),
            "shows": shows,
        }
