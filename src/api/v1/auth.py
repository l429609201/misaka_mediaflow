# app/api/v1/auth.py
# 认证 API — 登录 / 修改密码 / Token 验证 / 白名单检查

import logging
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.core.security import (
    ADMIN_USERNAME,
    get_admin_password_hash,
    verify_password,
    create_jwt_token,
    update_admin_password,
    verify_token,
    get_api_token,
    _check_ip_whitelist,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


class LoginPayload(BaseModel):
    username: str
    password: str


class ChangePasswordPayload(BaseModel):
    old_password: str
    new_password: str


@router.post("/login")
async def login(payload: LoginPayload):
    """
    用户名密码登录 → 返回 JWT Token
    """
    if payload.username != ADMIN_USERNAME:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    password_hash = get_admin_password_hash()
    if not verify_password(payload.password, password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    token = create_jwt_token(payload.username)
    logger.info("管理员登录成功: %s", payload.username)
    return {
        "token": token,
        "token_type": "bearer",
        "username": payload.username,
    }


@router.get("/verify")
async def verify(request: Request):
    """
    验证当前凭证是否有效（JWT Token 或 IP 白名单）
    白名单命中时自动签发 JWT，前端存储后后续请求都走 JWT
    """
    # 1. 先检查已有 JWT Token
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        from src.core.security import decode_jwt_token
        payload = decode_jwt_token(token)
        if payload and payload.get("sub"):
            return {"valid": True, "username": payload["sub"], "method": "jwt"}

        # 静态 API Token
        import hmac as _hmac
        if _hmac.compare_digest(token, get_api_token()):
            return {"valid": True, "username": ADMIN_USERNAME, "method": "api_token"}

    # 2. IP 白名单 → 自动签发 JWT Token
    client_ip = request.client.host if request.client else ""
    if _check_ip_whitelist(client_ip):
        token = create_jwt_token(ADMIN_USERNAME)
        logger.info("白名单 IP %s 自动登录", client_ip)
        return {
            "valid": True,
            "username": ADMIN_USERNAME,
            "method": "whitelist",
            "token": token,
        }

    return {"valid": False}


@router.post("/change-password", dependencies=[Depends(verify_token)])
async def change_password(payload: ChangePasswordPayload):
    """
    修改管理员密码（需要提供旧密码验证）
    """
    password_hash = get_admin_password_hash()
    if not verify_password(payload.old_password, password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="旧密码错误")

    if len(payload.new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码至少 6 位")

    update_admin_password(payload.new_password)
    logger.info("管理员密码已修改")
    return {"success": True, "message": "密码修改成功"}


@router.get("/me", dependencies=[Depends(verify_token)])
async def get_current_user(user: str = Depends(verify_token)):
    """获取当前登录用户信息"""
    return {
        "username": user if user != "api" else ADMIN_USERNAME,
        "role": "admin",
    }


@router.get("/api-token", dependencies=[Depends(verify_token)])
async def get_token():
    """获取静态 API Token（供外部程序调用）"""
    return {"api_token": get_api_token()}

