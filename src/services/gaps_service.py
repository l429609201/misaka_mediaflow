# src/services/gaps_service.py
# 缺集管理服务 — 阶段1同步Emby→DB(meta_series/season/episode)，阶段2 DB→TMDB比对

import json
import logging
from typing import Optional
from collections import defaultdict

from sqlalchemy import select, func

from src.core.timezone import tm
from src.db import get_async_session_local
from src.db.models.metadata import MetaSeries, MetaSeason, MetaEpisode

logger = logging.getLogger(__name__)


class GapsService:

    # ── 阶段1: 同步 Emby → DB ────────────────────────────────────────

    async def sync_emby(self, library_id: str = "") -> dict:
        """从 Emby 拉取 Series/Season/Episode 写入 meta_ 表"""
        from src.services.media_server_service import media_server_service

        adapter = await media_server_service.get_adapter()
        if not adapter:
            return {"error": "媒体服务器未连接"}

        libraries = await adapter.get_libraries()
        all_series = []
        for lib in libraries:
            lib_id = lib.get("ItemId", lib.get("Id", ""))
            if library_id and lib_id != library_id:
                continue
            try:
                items = await adapter.get_items(lib_id, item_type="Series")
                for s in items:
                    s["_library_id"] = lib_id
                all_series.extend(items)
            except Exception as e:
                logger.warning("[Gaps] 获取库 %s 失败: %s", lib_id, e)

        if not all_series:
            return {"error": "未找到剧集", "synced": 0}

        logger.info("[Gaps] 阶段1: 同步 %d 部剧集...", len(all_series))
        synced = 0
        skipped = 0

        for series in all_series:
            emby_sid = series.get("Id", "")
            name = series.get("Name", "")
            pids = series.get("ProviderIds", {})
            tmdb_id = int(pids.get("Tmdb") or pids.get("tmdb") or 0)
            imdb_id = pids.get("Imdb") or pids.get("imdb") or ""
            lib_id = series.get("_library_id", "")

            if not tmdb_id:
                skipped += 1
                continue

            try:
                # upsert MetaSeries
                async with get_async_session_local() as db:
                    row = (await db.execute(
                        select(MetaSeries).where(MetaSeries.emby_id == emby_sid)
                    )).scalars().first()
                    if row:
                        row.title = name
                        row.tmdb_id = tmdb_id
                        row.imdb_id = imdb_id
                        row.library_id = lib_id
                        row.synced_at = tm.now()
                        series_pk = row.id
                    else:
                        new_row = MetaSeries(
                            emby_id=emby_sid, title=name, media_type="Series",
                            tmdb_id=tmdb_id, imdb_id=imdb_id, library_id=lib_id,
                        )
                        db.add(new_row)
                        await db.flush()
                        series_pk = new_row.id
                    await db.commit()

                # 拉取 Episodes 并写入
                episodes = await adapter.get_items(emby_sid, item_type="Episode")
                season_eps = defaultdict(list)

                async with get_async_session_local() as db:
                    for ep in episodes:
                        sn = ep.get("ParentIndexNumber", 0)
                        en = ep.get("IndexNumber", 0)
                        if not sn or not en:
                            continue
                        season_eps[sn].append(en)
                        ep_emby_id = ep.get("Id", "")

                        existing = (await db.execute(
                            select(MetaEpisode).where(MetaEpisode.emby_id == ep_emby_id)
                        )).scalars().first()
                        if existing:
                            existing.season_number = sn
                            existing.episode_number = en
                            existing.title = ep.get("Name", "")
                            existing.file_path = ep.get("Path", "")
                            existing.source = "emby"
                            existing.synced_at = tm.now()
                        else:
                            db.add(MetaEpisode(
                                series_id=series_pk, emby_id=ep_emby_id,
                                season_number=sn, episode_number=en,
                                title=ep.get("Name", ""),
                                file_path=ep.get("Path", ""),
                                source="emby",
                            ))

                    # upsert MetaSeason 汇总
                    for sn, ep_list in season_eps.items():
                        existing_s = (await db.execute(
                            select(MetaSeason).where(
                                MetaSeason.series_id == series_pk,
                                MetaSeason.season_number == sn,
                            )
                        )).scalars().first()
                        if existing_s:
                            existing_s.emby_episodes = len(ep_list)
                            existing_s.synced_at = tm.now()
                        else:
                            db.add(MetaSeason(
                                series_id=series_pk, season_number=sn,
                                emby_episodes=len(ep_list),
                            ))

                    # 更新 series 的 emby_episodes
                    total_eps = sum(len(v) for v in season_eps.values())
                    s_row = await db.get(MetaSeries, series_pk)
                    if s_row:
                        s_row.emby_episodes = total_eps
                    await db.commit()

                # 日志
                detail = " ".join(
                    f"S{sn}:{{{','.join(str(e) for e in sorted(eps))}}}"
                    for sn, eps in sorted(season_eps.items())
                )
                logger.info("[Gaps] %s: %s", name, detail or "无集数")
                synced += 1

            except Exception as e:
                logger.warning("[Gaps] 同步 %s 失败: %s", name, e)

        logger.info("[Gaps] 阶段1完成: 同步 %d, 跳过 %d", synced, skipped)
        return {"synced": synced, "skipped_no_tmdb": skipped, "total": len(all_series)}

    # ── 阶段2: 从 DB 读取 → 比对 TMDB ────────────────────────────────

    async def scan_gaps(self, library_id: str = "") -> dict:
        """先同步 Emby→DB，再从 DB 读取比对 TMDB"""
        from src.services.metadata_service import metadata_service

        sync_result = await self.sync_emby(library_id)
        if sync_result.get("error"):
            return sync_result

        tmdb = await metadata_service.get_provider("tmdb")
        if not tmdb:
            return {"error": "TMDB 未配置"}

        logger.info("[Gaps] 阶段2: 从 DB 读取比对 TMDB...")
        async with get_async_session_local() as db:
            series_rows = (await db.execute(
                select(MetaSeries).where(MetaSeries.tmdb_id > 0, MetaSeries.media_type == "Series")
            )).scalars().all()

        gaps = []
        scanned = 0
        for s_row in series_rows:
            try:
                # 从 DB 读取该剧已有集数
                async with get_async_session_local() as db:
                    ep_rows = (await db.execute(
                        select(MetaEpisode).where(
                            MetaEpisode.series_id == s_row.id,
                            MetaEpisode.source == "emby",
                        )
                    )).scalars().all()
                emby_ep_set = {(ep.season_number, ep.episode_number) for ep in ep_rows}

                result = await self._compare_with_tmdb(
                    tmdb, s_row.title, s_row.tmdb_id, emby_ep_set, s_row.id,
                )
                scanned += 1
                if result and result.get("missing"):
                    gaps.append(result)
            except Exception as e:
                logger.warning("[Gaps] 比对失败 %s: %s", s_row.title, e)

        logger.info("[Gaps] 完成: %d 部, %d 部缺集, 跳过 %d",
                    scanned, len(gaps), sync_result.get("skipped_no_tmdb", 0))
        return {
            "total_series": scanned,
            "gaps_count": len(gaps),
            "skipped_no_tmdb": sync_result.get("skipped_no_tmdb", 0),
            "gaps": gaps,
        }

    # ── TMDB 比对 + 将 TMDB 信息回写 DB ──────────────────────────────

    async def _compare_with_tmdb(self, tmdb, series_name: str, tmdb_id: int,
                                  emby_ep_set: set, series_pk: int = 0) -> Optional[dict]:
        """与 TMDB 比对 + 回写 TMDB 元信息到 DB"""
        tv_detail = await tmdb.get_tv(tmdb_id)
        if not tv_detail:
            return None

        # 回写 TMDB 信息到 meta_series
        if series_pk:
            async with get_async_session_local() as db:
                s_row = await db.get(MetaSeries, series_pk)
                if s_row:
                    s_row.original_title = tv_detail.get("original_name", "")
                    s_row.overview = tv_detail.get("overview", "") or s_row.overview
                    s_row.poster_path = tv_detail.get("poster_path", "")
                    s_row.backdrop_path = tv_detail.get("backdrop_path", "")
                    s_row.status = tv_detail.get("status", "")
                    s_row.vote_average = tv_detail.get("vote_average", 0)
                    s_row.vote_count = tv_detail.get("vote_count", 0)
                    s_row.origin_country = ",".join(tv_detail.get("origin_country", []))
                    s_row.original_lang = tv_detail.get("original_language", "")
                    genres = [g.get("name", "") for g in tv_detail.get("genres", [])]
                    s_row.genres = json.dumps(genres, ensure_ascii=False)
                    s_row.scraped_at = tm.now()
                    s_row.scraped = 1
                await db.commit()

        # 比对每季
        tmdb_detail_parts = []
        missing = []
        total_tmdb = 0
        total_seasons = 0

        for season_info in tv_detail.get("seasons", []):
            season_num = season_info.get("season_number", 0)
            if season_num == 0:
                continue
            ep_count = season_info.get("episode_count", 0)
            total_tmdb += ep_count
            total_seasons += 1
            tmdb_detail_parts.append(f"S{season_num}:{ep_count}集")

            # 回写 TMDB 季信息到 meta_season
            if series_pk:
                async with get_async_session_local() as db:
                    s_season = (await db.execute(
                        select(MetaSeason).where(
                            MetaSeason.series_id == series_pk,
                            MetaSeason.season_number == season_num,
                        )
                    )).scalars().first()
                    if s_season:
                        s_season.tmdb_episodes = ep_count
                        s_season.title = season_info.get("name", "")
                        s_season.overview = season_info.get("overview", "")
                        s_season.poster_path = season_info.get("poster_path", "")
                        s_season.air_date = season_info.get("air_date", "")
                    else:
                        db.add(MetaSeason(
                            series_id=series_pk, season_number=season_num,
                            tmdb_episodes=ep_count,
                            title=season_info.get("name", ""),
                            overview=season_info.get("overview", ""),
                            poster_path=season_info.get("poster_path", ""),
                            air_date=season_info.get("air_date", ""),
                        ))
                    await db.commit()

            for ep_num in range(1, ep_count + 1):
                if (season_num, ep_num) not in emby_ep_set:
                    missing.append({"season": season_num, "episode": ep_num})

        # 回写总季数/集数
        if series_pk:
            async with get_async_session_local() as db:
                s_row = await db.get(MetaSeries, series_pk)
                if s_row:
                    s_row.total_seasons = total_seasons
                    s_row.total_episodes = total_tmdb
                await db.commit()

        logger.debug("[Gaps] %s TMDB: %s | 缺%d集", series_name, " ".join(tmdb_detail_parts), len(missing))

        if not missing:
            return None

        poster = tv_detail.get("poster_path", "")
        poster_url = f"https://image.tmdb.org/t/p/w300{poster}" if poster else ""

        return {
            "series_name": series_name,
            "tmdb_id": tmdb_id,
            "poster_url": poster_url,
            "total_episodes": total_tmdb,
            "owned_episodes": len(emby_ep_set),
            "missing_count": len(missing),
            "missing": missing,
        }
