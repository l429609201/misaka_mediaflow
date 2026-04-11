# src/services/gaps_service.py
# 缺集管理服务 — 阶段1同步Emby写DB，阶段2从DB读取比对TMDB

import json
import logging
from typing import Optional
from collections import defaultdict

from sqlalchemy import select, delete

from src.core.timezone import tm
from src.db import get_async_session_local
from src.db.models.gaps import GapsSeries

logger = logging.getLogger(__name__)


class GapsService:
    """缺集管理：阶段1同步Emby→DB，阶段2 DB→TMDB比对"""

    # ── 阶段1: 同步 Emby 数据到 DB ────────────────────────────────────

    async def sync_emby(self, library_id: str = "") -> dict:
        """从 Emby 拉取所有剧集的集数信息，写入 gaps_series 表"""
        from src.services.media_server_service import media_server_service

        adapter = await media_server_service.get_adapter()
        if not adapter:
            return {"error": "媒体服务器未连接"}

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
            return {"error": "未找到剧集", "synced": 0}

        logger.info("[Gaps] 阶段1: 同步 %d 部剧集到数据库...", len(series_list))
        synced = 0
        skipped_no_tmdb = 0

        for series in series_list:
            series_id = series.get("Id", "")
            series_name = series.get("Name", "")
            provider_ids = series.get("ProviderIds", {})
            tmdb_id_str = provider_ids.get("Tmdb") or provider_ids.get("tmdb") or ""
            imdb_id = provider_ids.get("Imdb") or provider_ids.get("imdb") or ""

            if not tmdb_id_str:
                skipped_no_tmdb += 1
                continue

            try:
                episodes = await adapter.get_items(series_id, item_type="Episode")
                season_eps = defaultdict(list)
                for ep in episodes:
                    s = ep.get("ParentIndexNumber", 0)
                    e = ep.get("IndexNumber", 0)
                    if s and e:
                        season_eps[s].append(e)

                # 排序
                seasons_dict = {sn: sorted(eps) for sn, eps in sorted(season_eps.items())}
                total_eps = sum(len(v) for v in seasons_dict.values())

                # 日志展示每季集数明细
                detail = " ".join(f"S{sn}:{{{','.join(str(e) for e in eps)}}}" for sn, eps in seasons_dict.items())
                logger.info("[Gaps] %s: %s", series_name, detail or "无集数")

                # upsert 到 DB
                async with get_async_session_local() as db:
                    row = (await db.execute(
                        select(GapsSeries).where(GapsSeries.series_id == series_id)
                    )).scalars().first()
                    if row:
                        row.series_name = series_name
                        row.tmdb_id = int(tmdb_id_str)
                        row.imdb_id = imdb_id
                        row.seasons_json = json.dumps(seasons_dict, ensure_ascii=False)
                        row.total_episodes = total_eps
                        row.synced_at = tm.now()
                    else:
                        db.add(GapsSeries(
                            series_id=series_id, series_name=series_name,
                            tmdb_id=int(tmdb_id_str), imdb_id=imdb_id,
                            seasons_json=json.dumps(seasons_dict, ensure_ascii=False),
                            total_episodes=total_eps,
                        ))
                    await db.commit()
                synced += 1
            except Exception as e:
                logger.warning("[Gaps] 同步 %s 失败: %s", series_name, e)

        logger.info("[Gaps] 阶段1完成: 同步 %d 部, 跳过无TMDB %d 部", synced, skipped_no_tmdb)
        return {"synced": synced, "skipped_no_tmdb": skipped_no_tmdb, "total": len(series_list)}

    # ── 阶段2: 从 DB 读取数据比对 TMDB ────────────────────────────────

    async def scan_gaps(self, library_id: str = "") -> dict:
        """先同步 Emby→DB，再从 DB 读取比对 TMDB"""
        from src.services.metadata_service import metadata_service

        # 阶段1
        sync_result = await self.sync_emby(library_id)
        if sync_result.get("error"):
            return sync_result

        tmdb = await metadata_service.get_provider("tmdb")
        if not tmdb:
            return {"error": "TMDB 未配置"}

        # 阶段2: 从 DB 读取
        logger.info("[Gaps] 阶段2: 从数据库读取比对 TMDB...")
        async with get_async_session_local() as db:
            rows = (await db.execute(select(GapsSeries).where(GapsSeries.tmdb_id > 0))).scalars().all()

        gaps = []
        scanned = 0
        for row in rows:
            try:
                seasons_dict = json.loads(row.seasons_json or "{}")
                emby_ep_set = set()
                for sn_str, eps in seasons_dict.items():
                    for e in eps:
                        emby_ep_set.add((int(sn_str), int(e)))

                result = await self._compare_with_tmdb(tmdb, row.series_name, row.tmdb_id, emby_ep_set)
                scanned += 1
                if result and result.get("missing"):
                    gaps.append(result)
            except Exception as e:
                logger.warning("[Gaps] TMDB 比对失败 %s: %s", row.series_name, e)

        logger.info("[Gaps] 扫描完成: %d 部, %d 部有缺集, 跳过无TMDB %d 部",
                    scanned, len(gaps), sync_result.get("skipped_no_tmdb", 0))
        return {
            "total_series": scanned,
            "gaps_count": len(gaps),
            "skipped_no_tmdb": sync_result.get("skipped_no_tmdb", 0),
            "gaps": gaps,
        }

    async def _compare_with_tmdb(self, tmdb, series_name: str, tmdb_id: int, emby_ep_set: set) -> Optional[dict]:
        """与 TMDB 比对单个剧集"""
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
