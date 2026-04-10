# src/services/actor_service.py
# 演员管理服务 — 清理/中文化/类型修正
#
# 参考 emby-toolkit 的 actor_utils.py:
# - 拉取演员: GET /emby/Persons + GET /emby/Items?IncludeItemTypes=Series,Movie
# - 写回: POST /emby/Items/{id} 更新 People 字段
# - 数据源: TMDB get_person_details + 豆瓣

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ActorService:
    """演员管理服务"""

    async def _get_emby(self):
        """获取 Emby 适配器和 httpx client"""
        from src.services.media_server_service import media_server_service
        adapter = await media_server_service.get_adapter()
        if not adapter:
            raise RuntimeError("媒体服务器未配置")
        client = await adapter._ensure_client()
        return adapter, client

    async def _get_tmdb(self):
        """获取 TMDB Provider"""
        from src.services.metadata_service import metadata_service
        provider = await metadata_service.get_provider("tmdb")
        return provider

    # ── 拉取 Emby 所有演员 ────────────────────────────────────────────

    async def get_all_persons(self, search: str = "", page: int = 1, size: int = 50) -> dict:
        """从 Emby 拉取演员列表（带搜索、分页、头像URL）"""
        adapter, client = await self._get_emby()
        params = {
            "Fields": "ProviderIds,Overview,PrimaryImageTag",
            "Limit": str(size),
            "StartIndex": str((page - 1) * size),
            "SortBy": "SortName",
            "SortOrder": "Ascending",
        }
        if search:
            params["SearchTerm"] = search
        resp = await client.get("/emby/Persons", params=params)
        if resp.status_code != 200:
            return {"items": [], "total": 0}
        data = resp.json()
        items_raw = data.get("Items", []) if isinstance(data, dict) else data
        total = data.get("TotalRecordCount", len(items_raw)) if isinstance(data, dict) else len(items_raw)
        host = adapter._host
        items = []
        for p in items_raw:
            pid = p.get("Id", "")
            tag = p.get("PrimaryImageTag", "")
            img = f"{host}/emby/Items/{pid}/Images/Primary?tag={tag}&maxWidth=120" if tag else ""
            items.append({
                "id": pid,
                "name": p.get("Name", ""),
                "provider_ids": p.get("ProviderIds", {}),
                "has_image": bool(tag),
                "image_url": img,
                "overview": p.get("Overview", ""),
                "type": p.get("Type", ""),
            })
        return {"items": items, "total": total}

    async def update_person(self, person_id: str, name: str = "", provider_ids: dict = None) -> dict:
        """编辑演员信息（名称、ProviderIds）"""
        _, client = await self._get_emby()
        # 先获取当前数据
        resp = await client.get(f"/emby/Items/{person_id}", params={"Fields": "ProviderIds,Overview"})
        if resp.status_code != 200:
            return {"success": False, "message": "演员不存在"}
        item = resp.json()
        if name:
            item["Name"] = name
        if provider_ids is not None:
            item["ProviderIds"] = {**item.get("ProviderIds", {}), **provider_ids}
        resp2 = await client.post(f"/emby/Items/{person_id}", json=item)
        return {"success": resp2.status_code in (200, 204)}

    async def get_media_with_people(self, item_types: str = "Series,Movie") -> list[dict]:
        """拉取所有带 People 字段的媒体"""
        _, client = await self._get_emby()
        resp = await client.get("/emby/Items", params={
            "IncludeItemTypes": item_types,
            "Recursive": "true",
            "Fields": "People,ProviderIds",
            "Limit": "50000",
        })
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("Items", [])

    # ── 黑户演员清理 ──────────────────────────────────────────────────

    async def find_orphan_actors(self) -> list[dict]:
        """找出没有关联任何媒体的"黑户"演员"""
        persons = await self.get_all_persons()
        media_items = await self.get_media_with_people()

        # 收集所有媒体中出现的演员名
        used_names = set()
        for item in media_items:
            for p in item.get("People", []):
                used_names.add(p.get("Name", ""))

        orphans = [p for p in persons if p["name"] not in used_names]
        return orphans

    # ── 幽灵演员检测 ──────────────────────────────────────────────────

    async def find_ghost_actors(self, limit: int = 100) -> list[dict]:
        """找出 TMDB 上查不到的演员"""
        persons = await self.get_all_persons()
        tmdb = await self._get_tmdb()
        ghosts = []
        checked = 0

        for p in persons:
            if checked >= limit:
                break
            tmdb_id = p.get("provider_ids", {}).get("Tmdb", "")
            if tmdb_id:
                continue  # 有 TMDB ID 的不算幽灵
            # 通过名字搜索
            if tmdb:
                try:
                    result = await tmdb.search_multi(p["name"])
                    found_person = any(
                        r.get("media_type") == "person"
                        for r in result.get("raw", [])
                    )
                    if not found_person:
                        ghosts.append(p)
                except Exception:
                    pass
            else:
                # 没有 TMDB 配置，无 TMDB ID 的都算幽灵
                ghosts.append(p)
            checked += 1

        return ghosts

    # ── 中文化演员名 ──────────────────────────────────────────────────

    async def translate_names(self, limit: int = 200) -> dict:
        """通过 TMDB translations 获取中文名写回 Emby"""
        tmdb = await self._get_tmdb()
        if not tmdb:
            return {"success": False, "message": "TMDB 未配置"}

        _, client = await self._get_emby()
        media_items = await self.get_media_with_people()
        translated = 0
        skipped = 0
        errors = 0

        for item in media_items[:limit]:
            people = item.get("People", [])
            changed = False
            for person in people:
                name = person.get("Name", "")
                tmdb_id = person.get("ProviderIds", {}).get("Tmdb", "")
                # 已经是中文名则跳过
                if _is_cjk(name):
                    skipped += 1
                    continue
                if not tmdb_id:
                    skipped += 1
                    continue
                # 查询 TMDB 中文翻译
                try:
                    cn_name = await self._get_person_cn_name(tmdb, tmdb_id)
                    if cn_name and cn_name != name:
                        person["Name"] = cn_name
                        changed = True
                        translated += 1
                    else:
                        skipped += 1
                except Exception as e:
                    logger.debug("翻译演员 %s 失败: %s", name, e)
                    errors += 1

            # 写回 Emby
            if changed:
                try:
                    item_id = item.get("Id", "")
                    await client.post(f"/emby/Items/{item_id}", json={
                        "Id": item_id,
                        "People": people,
                    })
                except Exception as e:
                    logger.warning("写回演员 %s 失败: %s", item_id, e)
                    errors += 1

        return {
            "success": True,
            "translated": translated,
            "skipped": skipped,
            "errors": errors,
        }

    async def _get_person_cn_name(self, tmdb, tmdb_id: str) -> Optional[str]:
        """从 TMDB 获取演员中文名"""
        try:
            data = await tmdb._get_with_fallback(
                f"/person/{tmdb_id}",
                {"language": "zh-CN", "append_to_response": "translations"},
            )
            # 优先用 zh-CN 的翻译名
            translations = data.get("translations", {}).get("translations", [])
            for tr in translations:
                if tr.get("iso_639_1") == "zh" and tr.get("iso_3166_1") == "CN":
                    cn_name = tr.get("data", {}).get("name", "")
                    if cn_name:
                        return cn_name
            # fallback: 主记录的 name(如果用 zh-CN 语言请求)
            main_name = data.get("name", "")
            if main_name and _is_cjk(main_name):
                return main_name
        except Exception as e:
            logger.debug("TMDB person %s 查询失败: %s", tmdb_id, e)
        return None

    # ── 演员清理(统一入口，供工作流调用) ─────────────────────────────────

    async def cleanup(self, mode: str = "ghost") -> dict:
        """清理演员 mode=orphan(黑户) / ghost(幽灵)"""
        if mode == "orphan":
            actors = await self.find_orphan_actors()
        elif mode == "ghost":
            actors = await self.find_ghost_actors()
        else:
            return {"success": False, "message": f"未知模式: {mode}"}

        # 暂不自动删除，只返回列表
        return {
            "success": True,
            "mode": mode,
            "count": len(actors),
            "actors": actors[:100],  # 最多返回100个
        }

    async def delete_person(self, person_id: str) -> dict:
        """从 Emby 删除指定演员"""
        _, client = await self._get_emby()
        resp = await client.delete(f"/emby/Items/{person_id}")
        if resp.status_code in (200, 204):
            return {"success": True}
        return {"success": False, "message": f"HTTP {resp.status_code}"}

    async def batch_delete_persons(self, person_ids: list[str]) -> dict:
        """批量删除演员"""
        success, failed = 0, 0
        for pid in person_ids:
            r = await self.delete_person(pid)
            if r.get("success"):
                success += 1
            else:
                failed += 1
        return {"success": True, "deleted": success, "failed": failed}


def _is_cjk(text: str) -> bool:
    """检测文本是否包含 CJK 字符"""
    for ch in text:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF or  # CJK Unified Ideographs
            0x3400 <= cp <= 0x4DBF or  # CJK Extension A
            0x3000 <= cp <= 0x303F or  # CJK Symbols
            0x3040 <= cp <= 0x309F or  # Hiragana
            0x30A0 <= cp <= 0x30FF):   # Katakana
            return True
    return False


# ── 全局单例 ──────────────────────────────────────────────────────────
_actor_service: Optional[ActorService] = None

def get_actor_service() -> ActorService:
    global _actor_service
    if _actor_service is None:
        _actor_service = ActorService()
    return _actor_service

# 便捷引用
actor_service = ActorService()
