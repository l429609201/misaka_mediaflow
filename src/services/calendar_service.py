# src/services/calendar_service.py
# 追剧日历服务 — TMDB 本周排期 + Emby 库交叉标记

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CalendarService:
    """追剧日历：获取本周热播剧集更新排期，标记库中已有/缺失"""

    async def get_weekly_calendar(self) -> dict:
        from src.services.metadata_service import metadata_service
        from src.services.media_server_service import media_server_service

        tmdb = await metadata_service.get_provider("tmdb")
        if not tmdb:
            return {"error": "TMDB 未配置", "days": []}

        # 获取 Emby 中所有剧集的 TMDB ID 集合
        owned_tmdb_ids = set()
        adapter = await media_server_service.get_adapter()
        if adapter:
            try:
                for lib in await adapter.get_libraries():
                    lib_id = lib.get("ItemId", lib.get("Id", ""))
                    items = await adapter.get_items(lib_id, item_type="Series")
                    for item in items:
                        tid = (item.get("ProviderIds") or {}).get("Tmdb")
                        if tid:
                            owned_tmdb_ids.add(str(tid))
            except Exception as e:
                logger.warning("[Calendar] 获取 Emby 库失败: %s", e)

        # 获取本周每天的 airing 数据
        today = datetime.utcnow().date()
        days = []
        for offset in range(7):
            date = today + timedelta(days=offset)
            date_str = date.isoformat()
            try:
                data = await tmdb._get("/tv/airing_today", params={"page": 1})
                shows = []
                for item in data.get("results", [])[:20]:
                    tmdb_id = str(item.get("id", ""))
                    shows.append({
                        "tmdb_id": tmdb_id,
                        "name": item.get("name", ""),
                        "original_name": item.get("original_name", ""),
                        "overview": (item.get("overview") or "")[:100],
                        "poster_url": f"https://image.tmdb.org/t/p/w200{item['poster_path']}" if item.get("poster_path") else "",
                        "vote_average": item.get("vote_average", 0),
                        "origin_country": item.get("origin_country", []),
                        "in_library": tmdb_id in owned_tmdb_ids,
                    })
                days.append({"date": date_str, "weekday": date.strftime("%A"), "shows": shows})
            except Exception as e:
                logger.warning("[Calendar] 获取 %s 数据失败: %s", date_str, e)
                days.append({"date": date_str, "weekday": date.strftime("%A"), "shows": []})
            # TMDB airing_today 不支持按日期查询，只返回今天的
            # 后续日期复用今天数据（实际生产需要用 changes API 或缓存）
            if offset > 0:
                break

        return {"days": days, "owned_count": len(owned_tmdb_ids)}

    async def get_airing_today(self) -> dict:
        """获取今日正在播出的剧集"""
        from src.services.metadata_service import metadata_service
        from src.services.media_server_service import media_server_service

        tmdb = await metadata_service.get_provider("tmdb")
        if not tmdb:
            return {"error": "TMDB 未配置", "shows": []}

        owned_tmdb_ids = set()
        adapter = await media_server_service.get_adapter()
        if adapter:
            try:
                for lib in await adapter.get_libraries():
                    lib_id = lib.get("ItemId", lib.get("Id", ""))
                    items = await adapter.get_items(lib_id, item_type="Series")
                    for item in items:
                        tid = (item.get("ProviderIds") or {}).get("Tmdb")
                        if tid:
                            owned_tmdb_ids.add(str(tid))
            except Exception as e:
                logger.warning("[Calendar] Emby 查询失败: %s", e)

        shows = []
        try:
            for page in range(1, 4):  # 最多3页
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

        # 按是否在库排序：在库的排前面
        shows.sort(key=lambda s: (not s["in_library"], -s["vote_average"]))
        return {
            "date": datetime.utcnow().date().isoformat(),
            "total": len(shows),
            "in_library": sum(1 for s in shows if s["in_library"]),
            "shows": shows,
        }
