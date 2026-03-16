# app/core/scheduler.py
# 定时任务管理 — 基于 APScheduler

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# 全局调度器实例
scheduler = AsyncIOScheduler()


def start_scheduler():
    """启动调度器"""
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler 已启动")


def shutdown_scheduler():
    """停止调度器"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler 已停止")


def add_cron_job(func, cron_expr: str, job_id: str, **kwargs):
    """
    添加 Cron 定时任务
    cron_expr: "0 3 * * *" 格式
    """
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        logger.error(f"无效的 cron 表达式: {cron_expr}")
        return

    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
    )

    # 如果 job 已存在则替换
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(func, trigger, id=job_id, **kwargs)
    logger.info(f"定时任务已注册: {job_id} ({cron_expr})")

