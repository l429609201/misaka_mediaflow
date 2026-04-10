# src/services/gaps_service.py
# 缺集管理服务 — TMDB vs Emby 比对

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class GapsService:
    """缺集管理：比对 Emby 库中的剧集与 TMDB 全量数据，找出缺失集数"""

    async def scan_gaps(self, library_id: str = "") -> dict:
        """
        扫描缺集。

        流程：
        1. 从 Emby 获取所有 Series
        2. 对每个 Series 通过 ProviderIds 获取 TMDB ID
        3. 从 TMDB 获取全量季/集信息
        4. 对比 Emby 中已有的集数，找出缺失
        """
        from src.services.media_server_service import media_server_service
        from src.services.metadata_service import metadata_service

        adapter = await media_server_service.get_adapter()
        if not adapter:
            return {"error": "媒体服务器未连接"}

        tmdb = await metadata_service.get_provider("tmdb")
        if not tmdb:
            return {"error": "TMDB 未配置"}

        # 获取 Emby 中的所有剧集
        libraries = await adapter.get_libraries()
        target_libs = [libraries] if not library_id else [
            [lib for lib in libraries if lib.get("ItemId") == library_id]
        ]

        series_list = []
        for lib in libraries:
            lib_id = lib.get("ItemId", lib.get("Id", ""))
            if library_id and lib_id != library_id:
                continue
            try:
                items = await adapter.get_items(lib_id, item_type="Series")
                series_list.extend(items)
            except Exception as e:
                logger.warning("[Gaps] 获取库 %s 失败: %s", lib_id, e)

        if not series_list:
            return {"error": "未找到剧集", "gaps": [], "total_series": 0}

        gaps = []
        scanned = 0
        for series in series_list:
            try:
                result = await self._check_series(adapter, tmdb, series)
                if result and result.get("missing"):
                    gaps.append(result)
                scanned += 1
            except Exception as e:
                logger.warning("[Gaps] 检查剧集失败 %s: %s", series.get("Name", ""), e)

        logger.info("[Gaps] 扫描完成: %d 部剧集, %d 部有缺集", scanned, len(gaps))
        return {
            "total_series": scanned,
            "gaps_count": len(gaps),
            "gaps": gaps,
        }

    async def _check_series(self, adapter, tmdb, series: dict) -> Optional[dict]:
        """检查单个剧集的缺集情况"""
        series_name = series.get("Name", "")
        series_id = series.get("Id", "")
        provider_ids = series.get("ProviderIds", {})
        tmdb_id = provider_ids.get("Tmdb") or provider_ids.get("tmdb")

        if not tmdb_id:
            return None

        tmdb_id = int(tmdb_id)

        # 从 TMDB 获取完整季/集信息
        tv_detail = await tmdb.get_tv(tmdb_id)
        if not tv_detail:
            return None

        # 获取 Emby 中这个系列的所有集
        emby_episodes = await adapter.get_items(series_id, item_type="Episode")
        emby_ep_set = set()
        for ep in emby_episodes:
            s = ep.get("ParentIndexNumber", 0)  # season
            e = ep.get("IndexNumber", 0)        # episode
            if s and e:
                emby_ep_set.add((s, e))

        # 对比 TMDB 的每一季
        missing = []
        total_tmdb = 0
        for season_info in tv_detail.get("seasons", []):
            season_num = season_info.get("season_number", 0)
            if season_num == 0:  # 跳过特别篇
                continue
            ep_count = season_info.get("episode_count", 0)
            total_tmdb += ep_count

            for ep_num in range(1, ep_count + 1):
                if (season_num, ep_num) not in emby_ep_set:
                    missing.append({
                        "season": season_num,
                        "episode": ep_num,
                    })

        if not missing:
            return None

        poster = tv_detail.get("poster_path", "")
        poster_url = f"https://image.tmdb.org/t/p/w300{poster}" if poster else ""

        return {
            "series_name": series_name,
            "series_id": series_id,
            "tmdb_id": tmdb_id,
            "poster_url": poster_url,
            "total_episodes": total_tmdb,
            "owned_episodes": len(emby_ep_set),
            "missing_count": len(missing),
            "missing": missing,
        }
