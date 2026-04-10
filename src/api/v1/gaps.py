# src/api/v1/gaps.py
# 缺集管理 API

from fastapi import APIRouter, Depends

from src.core.security import verify_token
from src.services.gaps_service import GapsService

router = APIRouter(prefix="/gaps", tags=["缺集管理"])
_gaps_svc = GapsService()


@router.get("/scan", dependencies=[Depends(verify_token)])
async def scan_gaps(library_id: str = ""):
    """扫描缺集：TMDB vs Emby 比对"""
    return await _gaps_svc.scan_gaps(library_id)
