"""认证服务：登录、刷新、登出、当前用户（接口 1–3）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import BizError, Codes
from app.core.permissions import ALL_WAREHOUSE_ROLES, MATRIX, ROLE_LABELS
from app.core.redis import rds
from app.core.security import (
    blacklist,
    decode_token,
    is_blacklisted,
    make_access_token,
    make_refresh_token,
    verify_captcha,
    verify_password,
)
from app.domain.enums import UserStatus
from app.domain.models import User, UserWarehouse, Warehouse
from app.domain.rules import mask_phone
from app.schemas.auth import LoginReq, LoginResp, MeResp

_LANDING = {"ADMIN": "/basedata/warehouse"}


def _warehouses_of(db: Session, user: User) -> list[dict]:
    if user.role in ALL_WAREHOUSE_ROLES:
        rows = db.execute(select(Warehouse.id, Warehouse.name).where(Warehouse.status == "ENABLED")).all()
    else:
        rows = db.execute(
            select(Warehouse.id, Warehouse.name)
            .join(UserWarehouse, UserWarehouse.warehouse_id == Warehouse.id)
            .where(UserWarehouse.user_id == user.id, Warehouse.status == "ENABLED")
        ).all()
    return [{"id": r[0], "name": r[1]} for r in rows]


def _permissions_of(user: User) -> list[str]:
    return sorted(k for k, roles in MATRIX.items() if user.role in roles)


def login(db: Session, req: LoginReq, ip: str = "-") -> LoginResp:
    verify_captcha(req.captcha_id, req.captcha)

    user = db.execute(select(User).where(User.username == req.username)).scalar_one_or_none()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if user is not None and user.locked_until and user.locked_until > now:
        left = int((user.locked_until - now).total_seconds() // 60) + 1
        raise BizError(Codes.BIZ_RULE, f"密码连续错误已达上限，账号锁定中，请 {left} 分钟后重试",
                       data={"locked_until": user.locked_until.isoformat() + "Z"})

    if user is None or not verify_password(req.password, user.password):
        if user is not None:
            user.fail_count = (user.fail_count or 0) + 1
            if user.fail_count >= settings.login_fail_max:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                user.fail_count = 0
                db.commit()
                raise BizError(
                    Codes.BIZ_RULE,
                    f"密码连续错误 {settings.login_fail_max} 次，账号已锁定 "
                    f"{settings.login_lock_minutes} 分钟",
                    data={"locked_until": user.locked_until.isoformat() + "Z"},
                )
            db.commit()
        raise BizError(Codes.BIZ_RULE, "用户名或密码错误")

    if user.status != UserStatus.ENABLED:
        raise BizError(Codes.FORBIDDEN, "账号已停用，请联系管理员")

    user.fail_count = 0
    user.locked_until = None
    db.commit()

    access = make_access_token(user.id, user.role)
    refresh = make_refresh_token(user.id)
    rds.set(f"sess:{decode_token(access)['jti']}", "1", ex=settings.idle_ttl)

    return LoginResp(
        access_token=access,
        expires_in=settings.access_ttl,
        refresh_token=refresh,
        refresh_expires_in=settings.refresh_ttl,
        user={
            "id": user.id,
            "name": user.name,
            "role": user.role,
            "warehouses": _warehouses_of(db, user),
        },
        landing=_LANDING.get(user.role, "/"),
    )


def refresh(db: Session, token: str) -> dict:
    payload = decode_token(token, typ="refresh")
    user = db.get(User, int(payload["sub"]))
    if user is None or user.status != UserStatus.ENABLED:
        raise BizError(Codes.UNAUTHORIZED, "账号不存在或已停用")
    access = make_access_token(user.id, user.role)
    rds.set(f"sess:{decode_token(access)['jti']}", "1", ex=settings.idle_ttl)
    return {
        "access_token": access,
        "expires_in": settings.access_ttl,
        "refresh_token": make_refresh_token(user.id),
    }


def logout(token: str) -> None:
    try:
        payload = decode_token(token)
    except BizError:
        return  # 已过期的 token 无需拉黑
    blacklist(payload["jti"], int(payload["exp"]))
    rds.delete(f"sess:{payload['jti']}")


def me(db: Session, user: User) -> MeResp:
    return MeResp(
        id=user.id,
        username=user.username,
        name=user.name,
        phone=mask_phone(user.phone),
        role=user.role,
        role_label=ROLE_LABELS.get(user.role, user.role),
        permissions=_permissions_of(user),
        warehouses=_warehouses_of(db, user),
    )
