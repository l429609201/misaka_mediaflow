# app/services/strm_service.py
# STRM 生成服务

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_async_session_local
from src.db.models import StrmTask, StrmFile, MediaItem
from src.core.config import settings
from src.core.timezone import tm

logger = logging.getLogger(__name__)


class StrmService:
    """STRM 生成业务逻辑"""

    async def create_task(self, task_type: str = "manual") -> dict:
        """创建 STRM 生成任务并在后台执行"""
        async with get_async_session_local() as db:
            # 统计需要处理的媒体条目
            count_result = await db.execute(
                select(func.count()).select_from(MediaItem).where(
                    MediaItem.item_type.in_(["Movie", "Episode"])
                )
            )
            total = count_result.scalar() or 0

            task = StrmTask(
                task_type=task_type,
                status="running",
                total_items=total,
                started_at=tm.now(),
            )
            await task.async_create(db)
            await db.commit()
            task_id = task.id

        # 后台执行
        asyncio.create_task(self.run_task(task_id))
        logger.info("STRM 任务已创建: id=%d, total=%d", task_id, total)
        return {"task_id": task_id, "status": "running", "total_items": total}

    async def run_task(self, task_id: int):
        """执行 STRM 生成任务"""
        logger.info("执行 STRM 任务: id=%d", task_id)
        created = 0
        skipped = 0
        errors = 0
        error_msg = ""

        try:
            async with get_async_session_local() as db:
                # 查询所有可处理的媒体条目
                result = await db.execute(
                    select(MediaItem).where(
                        MediaItem.item_type.in_(["Movie", "Episode"]),
                        MediaItem.file_path != "",
                    )
                )
                items = result.scalars().all()

                output_dir = Path(settings.strm.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)

                for item in items:
                    try:
                        result = await self._generate_single_strm(db, item, output_dir, task_id)
                        if result == "created":
                            created += 1
                        elif result == "skipped":
                            skipped += 1
                    except Exception as e:
                        errors += 1
                        logger.error("STRM 生成失败: item_id=%s, err=%s", item.item_id, e)

                await db.commit()

        except Exception as e:
            error_msg = str(e)
            logger.error("STRM 任务异常: %s", e)

        # 更新任务状态
        async with get_async_session_local() as db:
            result = await db.execute(select(StrmTask).where(StrmTask.id == task_id))
            task = result.scalars().first()
            if task:
                task.status = "failed" if error_msg else "completed"
                task.processed = created + skipped + errors
                task.created_count = created
                task.skipped_count = skipped
                task.error_count = errors
                task.error_message = error_msg
                task.finished_at = tm.now()
                await db.commit()

        logger.info("STRM 任务完成: id=%d, created=%d, skipped=%d, errors=%d",
                     task_id, created, skipped, errors)

    async def _generate_single_strm(
        self, db: AsyncSession, item: MediaItem, output_dir: Path, task_id: int
    ) -> str:
        """生成单个 STRM 文件，返回 'created' 或 'skipped'"""
        # 构造 STRM 文件路径（保持目录结构）
        relative_path = item.file_path.lstrip("/")
        strm_path = output_dir / Path(relative_path).with_suffix(".strm")

        # 已存在则跳过
        if strm_path.exists():
            return "skipped"

        # 生成 STRM 内容
        strm_content = self._build_strm_content(item)

        # 写入文件
        strm_path.parent.mkdir(parents=True, exist_ok=True)
        strm_path.write_text(strm_content, encoding="utf-8")

        # 记录数据库
        strm_file = StrmFile(
            task_id=task_id,
            item_id=item.item_id,
            strm_path=str(strm_path),
            strm_content=strm_content,
            strm_mode=settings.strm.mode,
            file_size=item.file_size,
        )
        db.add(strm_file)

        return "created"

    def _build_strm_content(self, item: MediaItem) -> str:
        """根据模式构造 STRM 内容"""
        mode = settings.strm.mode
        external_url = settings.server.external_url.rstrip("/")

        if mode == "proxy" and external_url:
            # 302 代理模式 — 指向 Go 反代
            return f"{external_url}/emby/videos/{item.item_id}/stream?static=true"

        elif mode == "direct":
            # 直接路径模式
            return item.file_path

        elif mode == "p115" and item.pick_code:
            # ⭐ 115 直链模式 — STRM 直接指向 Go 代理 /p115/play/<pick_code>/<filename>
            # Go 代理收到后: 查缓存 → 未命中调 Python 获取直链 → 302 到 115 CDN
            link_host = self._get_strm_link_host() or external_url
            if not link_host:
                link_host = f"http://127.0.0.1:{settings.server.go_port}"
            link_host = link_host.rstrip("/")
            # 用文件名（不含路径）作为 URL 尾部，便于播放器识别格式
            from pathlib import Path as _Path
            filename = _Path(item.file_path).name if item.file_path else f"{item.item_id}.mkv"
            return f"{link_host}/p115/play/{item.pick_code}/{filename}"

        elif mode == "p115_path":
            # 115 本地路径模式
            return item.file_path

        else:
            # 默认使用文件路径
            return item.file_path

    @staticmethod
    def _get_strm_link_host() -> str:
        """
        从数据库读取 p115_settings 中的 strm_link_host。
        这是用户在 115 设置页面配置的"STRM 链接地址"（Go 反代对外访问地址）。
        """
        import asyncio, json as _json

        async def _fetch() -> str:
            from sqlalchemy import select as _select
            from src.db import get_async_session_local as _get_sess
            from src.db.models.system import SystemConfig as _SC
            try:
                async with _get_sess() as db:
                    row = await db.execute(
                        _select(_SC).where(_SC.key == "p115_settings")
                    )
                    cfg = row.scalars().first()
                    if cfg and cfg.value:
                        data = _json.loads(cfg.value)
                        return (data.get("strm_link_host") or "").strip().rstrip("/")
            except Exception:
                pass
            return ""

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 异步上下文中用 run_coroutine_threadsafe 或直接返回空（由调用方处理）
                # 此处退化：返回空，让调用方使用 external_url / go_port 兜底
                return ""
            return loop.run_until_complete(_fetch())
        except Exception:
            return ""

    async def get_task_status(self, task_id: int) -> dict:
        """获取任务状态"""
        async with get_async_session_local() as db:
            result = await db.execute(select(StrmTask).where(StrmTask.id == task_id))
            task = result.scalars().first()
            if not task:
                return {"error": "task not found"}
            return task.to_dict()

    async def list_tasks(self, page: int = 1, size: int = 20) -> dict:
        """分页查询任务列表"""
        async with get_async_session_local() as db:
            # 总数
            count_result = await db.execute(select(func.count()).select_from(StrmTask))
            total = count_result.scalar() or 0
            # 分页
            result = await db.execute(
                select(StrmTask)
                .order_by(StrmTask.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
            tasks = result.scalars().all()
            return {
                "items": [t.to_dict() for t in tasks],
                "total": total,
                "page": page,
                "size": size,
            }

    async def list_files(self, task_id: int = 0, page: int = 1, size: int = 20) -> dict:
        """分页查询 STRM 文件列表"""
        async with get_async_session_local() as db:
            query = select(StrmFile)
            count_query = select(func.count()).select_from(StrmFile)
            if task_id > 0:
                query = query.where(StrmFile.task_id == task_id)
                count_query = count_query.where(StrmFile.task_id == task_id)

            count_result = await db.execute(count_query)
            total = count_result.scalar() or 0

            result = await db.execute(
                query.order_by(StrmFile.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
            files = result.scalars().all()
            return {
                "items": [f.to_dict() for f in files],
                "total": total,
                "page": page,
                "size": size,
            }

