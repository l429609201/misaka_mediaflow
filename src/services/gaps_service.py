# src/services/gaps_service.py
# 缺集管理服务 — 先同步 Emby 数据再批量请求 TMDB 比对

import logging
from typing import Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class GapsService:
    """缺集管理：先全量同步 Emby 库数据，再批量请求 TMDB 比对"""

    async def scan_gaps(self, library_id: str = "") -> dict:
        from src.services.media_server_service import media_server_service
        from src.services.metadata_service import metadata_service

        adapter = await media_server_service.get_adapter()
        if not adapter:
            return {"error": "媒体服务器未连接"}
        tmdb = await metadata_service.get_provider("tmdb")
        if not tmdb:
            return {"error": "TMDB 未配置"}

        # ── 阶段1: 全量同步 Emby 数据 ─────────────────────────────────
        logger.info("[Gaps] 阶段1: 同步 Emby 剧集数据...")

        libraries = await adapter.get_libraries()
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

        logger.info("[Gaps] 同步完成: 共 %d 部剧集", len(series_list))

        # 预拉取所有剧集的 Episode 数据（按 series 分组）
        emby_data = {}  # { series_id: { "name": str, "tmdb_id": int, "episodes": {(s,e)} } }
        skipped_no_tmdb = 0

        for series in series_list:
            series_id = series.get("Id", "")
            series_name = series.get("Name", "")
            provider_ids = series.get("ProviderIds", {})
            tmdb_id = provider_ids.get("Tmdb") or provider_ids.get("tmdb")

            if not tmdb_id:
                skipped_no_tmdb += 1
                continue

            try:
                episodes = await adapter.get_items(series_id, item_type="Episode")
                ep_set = set()
                season_eps = defaultdict(list)  # { season_num: [ep_nums] }
                for ep in episodes:
                    s = ep.get("ParentIndexNumber", 0)
                    e = ep.get("IndexNumber", 0)
                    if s and e:
                        ep_set.add((s, e))
                        season_eps[s].append(e)

                # 日志展示每季的集数明细
                detail_parts = []
                for sn in sorted(season_eps.keys()):
                    eps_sorted = sorted(season_eps[sn])
                    detail_parts.append(f"S{sn}:{{{','.join(str(e) for e in eps_sorted)}}}")
                logger.info("[Gaps] %s: %s", series_name, " ".join(detail_parts) if detail_parts else "无集数")

                emby_data[series_id] = {
                    "name": series_name,
                    "tmdb_id": int(tmdb_id),
                    "episodes": ep_set,
                    "provider_ids": provider_ids,
                }
            except Exception as e:
                logger.warning("[Gaps] 获取 %s 集数失败: %s", series_name, e)

        logger.info("[Gaps] 阶段1完成: %d 部有TMDB ID, %d 部无TMDB ID跳过", len(emby_data), skipped_no_tmdb)

        # ── 阶段2: 批量请求 TMDB 比对 ────────────────────────────────
        logger.info("[Gaps] 阶段2: 请求 TMDB 比对缺集...")
        gaps = []
        scanned = 0

        for series_id, info in emby_data.items():
            try:
                result = await self._compare_with_tmdb(tmdb, info)
                scanned += 1
                if result and result.get("missing"):
                    gaps.append(result)
            except Exception as e:
                logger.warning("[Gaps] TMDB 比对失败 %s: %s", info["name"], e)

        logger.info("[Gaps] 扫描完成: %d 部剧集, %d 部有缺集, %d 部无TMDB ID跳过",
                    scanned, len(gaps), skipped_no_tmdb)
        return {
            "total_series": scanned,
            "gaps_count": len(gaps),
            "skipped_no_tmdb": skipped_no_tmdb,
            "gaps": gaps,
        }

    async def _compare_with_tmdb(self, tmdb, info: dict) -> Optional[dict]:
        """与 TMDB 比对单个剧集"""
        series_name = info["name"]
        tmdb_id = info["tmdb_id"]
        emby_ep_set = info["episodes"]

        tv_detail = await tmdb.get_tv(tmdb_id)
        if not tv_detail:
            return None

        # TMDB 每季集数明细
        tmdb_detail_parts = []
        missing = []
        total_tmdb = 0

        for season_info in tv_detail.get("seasons", []):
            season_num = season_info.get("season_number", 0)
            if season_num == 0:
                continue
            ep_count = season_info.get("episode_count", 0)
            total_tmdb += ep_count
            tmdb_detail_parts.append(f"S{season_num}:{ep_count}集")

            for ep_num in range(1, ep_count + 1):
                if (season_num, ep_num) not in emby_ep_set:
                    missing.append({"season": season_num, "episode": ep_num})

        logger.debug("[Gaps] %s TMDB: %s | 缺%d集", series_name, " ".join(tmdb_detail_parts), len(missing))

        if not missing:
            return None

        poster = tv_detail.get("poster_path", "")
        poster_url = f"https://image.tmdb.org/t/p/w300{poster}" if poster else ""

        return {
            "series_name": series_name,
            "series_id": "",
            "tmdb_id": tmdb_id,
            "poster_url": poster_url,
            "total_episodes": total_tmdb,
            "owned_episodes": len(emby_ep_set),
            "missing_count": len(missing),
            "missing": missing,
        }
