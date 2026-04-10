# src/api/v1/calendar.py
# 追剧日历 API

from fastapi import APIRouter, Depends
from src.core.security import verify_token
from src.services.calendar_service import CalendarService

router = APIRouter(prefix="/calendar", tags=["追剧日历"])
_cal_svc = CalendarService()


@router.get("/today", dependencies=[Depends(verify_token)])
async def airing_today():
    """获取今日正在播出的剧集（含 Emby 库标记）"""
    return await _cal_svc.get_airing_today()
