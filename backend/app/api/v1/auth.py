"""认证接口（接口文档 1–3）。登录/刷新/验证码不走幂等中间件。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.deps import CurrentUser, DbDep, bearer
from app.core.errors import Codes, BizError, ok
from app.core.security import make_captcha
from app.schemas.auth import CaptchaResp, LoginReq, LoginResp, MeResp, RefreshReq
from app.service import auth_service

router = APIRouter(prefix="/auth", tags=["认证"])


@router.get("/captcha", response_model=None, summary="图形验证码")
def captcha(request: Request) -> dict:
    return ok(make_captcha(), trace_id=request.state.trace_id)


@router.post("/login", summary="账号密码登录")
def login(request: Request, db: DbDep, body: LoginReq) -> dict:
    return ok(
        auth_service.login(db, body, request.client.host if request.client else "-"),
        trace_id=request.state.trace_id,
    )


@router.post("/refresh", summary="刷新 access token")
def refresh_token(request: Request, db: DbDep, body: RefreshReq) -> dict:
    return ok(auth_service.refresh(db, body.refresh_token), trace_id=request.state.trace_id)


@router.post("/logout", summary="登出并拉黑当前 token")
def logout(
    request: Request,
    db: DbDep,
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if cred is None:
        raise BizError(Codes.UNAUTHORIZED, "未登录")
    auth_service.logout(cred.credentials)
    return ok({"ok": True}, trace_id=request.state.trace_id)


@router.get("/me", summary="当前用户与权限")
def me(request: Request, db: DbDep, user: CurrentUser) -> dict:
    return ok(auth_service.me(db, user), trace_id=request.state.trace_id)
