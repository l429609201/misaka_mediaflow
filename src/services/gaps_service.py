# src/services/gaps_service.py
# 缺集管理服务 — 阶段1同步Emby→DB(meta_series/season/episode)，阶段2 DB→TMDB比对

import json
import logging
from typing import Optional
from collections import defaultdict

from sqlalchemy import select

from src.core.timezone import tm
from src.db import get_async_session_local
from src.db.models.metadata import MetaSeries, MetaSeason, MetaEpisode

logger = logging.getLogger(__name__)


class GapsService:

    # ── 阶段1: 同步 Emby → DB ────────────────────────────────────────

    async def sync_emby(self, library_id: str = "", task_id: int = 0) -> dict:
        """从 Emby 拉取 Series/Season/Episode 写入 meta_ 表"""
        from src.services.media_server_service import media_server_service
        from src.services.task_manager import get_task_manager
        tm = get_task_manager()

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
        total = len(all_series)

        for idx, series in enumerate(all_series):
            emby_sid = series.get("Id", "")
            name = series.get("Name", "")

            if task_id:
                tm.update_progress(task_id, f"同步 {idx+1}/{total}: {name}", {
                    "created": synced, "skipped": skipped, "errors": 0,
                })

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

    # ── 阶段2: 从 DB 读取 → 动态选择搜索源比对 ──────────────────────

    async def scan_gaps(self, library_id: str = "", task_id: int = 0) -> dict:
        """先同步 Emby→DB，再从 DB 读取，动态选择已启用的搜索源比对"""
        from src.services.metadata_service import metadata_service
        from src.services.task_manager import get_task_manager
        tm = get_task_manager()

        # 阶段1: 同步
        if task_id:
            tm.update_progress(task_id, "阶段1: 同步 Emby", {"created": 0, "skipped": 0, "errors": 0})
        sync_result = await self.sync_emby(library_id, task_id=task_id)
        if sync_result.get("error"):
            return sync_result

        # 阶段2: 比对
        if task_id:
            tm.update_progress(task_id, "阶段2: 比对搜索源", {"created": 0, "skipped": sync_result.get("skipped_no_tmdb", 0), "errors": 0})

        logger.info("[Gaps] 阶段2: 从 DB 读取，动态选择搜索源比对...")
        async with get_async_session_local() as db:
            series_rows = (await db.execute(
                select(MetaSeries).where(MetaSeries.media_type == "Series")
            )).scalars().all()

        total = len(series_rows)
        gaps = []
        scanned = 0
        skipped_no_id = 0
        for idx, s_row in enumerate(series_rows):
            # 构建该剧的 provider_ids
            provider_ids = {}
            if s_row.tmdb_id:
                provider_ids["tmdb"] = s_row.tmdb_id
            if s_row.tvdb_id:
                provider_ids["tvdb"] = s_row.tvdb_id

            if not provider_ids:
                skipped_no_id += 1
                if task_id:
                    tm.update_progress(task_id, f"比对中 {idx+1}/{total}: {s_row.title}", {
                        "created": len(gaps), "skipped": skipped_no_id, "errors": 0,
                    })
                continue

            try:
                if task_id:
                    tm.update_progress(task_id, f"比对中 {idx+1}/{total}: {s_row.title}", {
                        "created": len(gaps), "skipped": skipped_no_id, "errors": 0,
                    })

                # 从 DB 读取该剧已有集数
                async with get_async_session_local() as db:
                    ep_rows = (await db.execute(
                        select(MetaEpisode).where(
                            MetaEpisode.series_id == s_row.id,
                            MetaEpisode.source == "emby",
                        )
                    )).scalars().all()
                emby_ep_set = {(ep.season_number, ep.episode_number) for ep in ep_rows}

                # 动态获取 TV 季/集信息
                tv_detail, used_provider = await metadata_service.get_tv_seasons_dynamic(provider_ids)
                if not tv_detail:
                    scanned += 1
                    continue

                result = await self._compare_with_provider(
                    tv_detail, used_provider, s_row.title, emby_ep_set, s_row.id,
                )
                scanned += 1
                if result and result.get("missing"):
                    gaps.append(result)
            except Exception as e:
                logger.warning("[Gaps] 比对失败 %s: %s", s_row.title, e)

        logger.info("[Gaps] 完成: %d 部, %d 部缺集, 跳过 %d",
                    scanned, len(gaps), skipped_no_id)
        return {
            "total_series": scanned,
            "gaps_count": len(gaps),
            "skipped_no_tmdb": skipped_no_id,
            "gaps": gaps,
        }

    # ── 动态 Provider 比对 + 回写 DB ──────────────────────────────

    async def _compare_with_provider(self, tv_detail: dict, provider_name: str,
                                      series_name: str, emby_ep_set: set,
                                      series_pk: int = 0) -> Optional[dict]:
        """与搜索源返回的 tv_detail 比对 + 回写元信息到 DB"""

        # 回写搜索源信息到 meta_series
        if series_pk:
            async with get_async_session_local() as db:
                s_row = await db.get(MetaSeries, series_pk)
                if s_row:
                    s_row.original_title = tv_detail.get("original_name", "") or s_row.original_title
                    s_row.overview = tv_detail.get("overview", "") or s_row.overview
                    s_row.poster_path = tv_detail.get("poster_path", "") or s_row.poster_path
                    s_row.backdrop_path = tv_detail.get("backdrop_path", "") or s_row.backdrop_path
                    s_row.status = tv_detail.get("status", "") or s_row.status
                    s_row.vote_average = tv_detail.get("vote_average", 0) or s_row.vote_average
                    s_row.vote_count = tv_detail.get("vote_count", 0) or s_row.vote_count
                    oc = tv_detail.get("origin_country")
                    if oc:
                        s_row.origin_country = ",".join(oc) if isinstance(oc, list) else str(oc)
                    s_row.original_lang = tv_detail.get("original_language", "") or s_row.original_lang
                    genres = tv_detail.get("genres", [])
                    if genres:
                        genre_names = [g.get("name", "") if isinstance(g, dict) else str(g) for g in genres]
                        s_row.genres = json.dumps(genre_names, ensure_ascii=False)
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

            # 回写季信息到 meta_season
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

        logger.debug("[Gaps] %s [%s]: %s | 缺%d集", series_name, provider_name, " ".join(tmdb_detail_parts), len(missing))

        if not missing:
            return None

        poster = tv_detail.get("poster_path", "")
        if poster and poster.startswith("/"):
            poster_url = f"https://image.tmdb.org/t/p/w300{poster}"
        else:
            poster_url = poster or ""

        return {
            "series_name": series_name,
            "source": provider_name,
            "poster_url": poster_url,
            "total_episodes": total_tmdb,
            "owned_episodes": len(emby_ep_set),
            "missing_count": len(missing),
            "missing": missing,
        }


    # ── 从 DB 读取已同步的缺集数据（不触发扫描） ──────────────────

    async def get_gaps_from_db(self) -> dict:
        """直接从 meta_series/season 表读取缺集数据，前端打开页面时调用"""
        async with get_async_session_local() as db:
            series_rows = (await db.execute(
                select(MetaSeries).where(
                    MetaSeries.media_type == "Series",
                    MetaSeries.scraped == 1,  # 只取已刮削的
                )
            )).scalars().all()

        if not series_rows:
            return {"total_series": 0, "gaps_count": 0, "gaps": [], "synced": False}

        gaps = []
        for s in series_rows:
            if not s.total_episodes or not s.emby_episodes:
                continue
            missing_count = s.total_episodes - s.emby_episodes
            if missing_count <= 0:
                continue

            # 从 season 表取每季的缺集详情
            async with get_async_session_local() as db:
                seasons = (await db.execute(
                    select(MetaSeason).where(MetaSeason.series_id == s.id).order_by(MetaSeason.season_number)
                )).scalars().all()

            missing = []
            for sn in seasons:
                if sn.tmdb_episodes and sn.emby_episodes is not None:
                    diff = sn.tmdb_episodes - (sn.emby_episodes or 0)
                    if diff > 0:
                        # 找出该季缺失的具体集号
                        async with get_async_session_local() as db:
                            owned_eps = (await db.execute(
                                select(MetaEpisode.episode_number).where(
                                    MetaEpisode.series_id == s.id,
                                    MetaEpisode.season_number == sn.season_number,
                                    MetaEpisode.source == "emby",
                                )
                            )).scalars().all()
                        owned_set = set(owned_eps)
                        for ep in range(1, sn.tmdb_episodes + 1):
                            if ep not in owned_set:
                                missing.append({"season": sn.season_number, "episode": ep})

            if not missing:
                continue

            poster_url = ""
            if s.poster_path:
                poster_url = f"https://image.tmdb.org/t/p/w300{s.poster_path}" if s.poster_path.startswith("/") else s.poster_path

            gaps.append({
                "series_name": s.title,
                "tmdb_id": s.tmdb_id,
                "poster_url": poster_url,
                "total_episodes": s.total_episodes,
                "owned_episodes": s.emby_episodes,
                "missing_count": len(missing),
                "missing": missing,
            })

        return {
            "total_series": len(series_rows),
            "gaps_count": len(gaps),
            "gaps": gaps,
            "synced": True,
        }