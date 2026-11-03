"""依赖注入：db session、当前用户、角色权限、数据权限（接口文档 1.4）。

数据权限在这里强制注入，不接受前端传 warehouse_id 绕过——这是越权防护的唯一位置。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_session
from app.core.errors import BizError, Codes
from app.core.permissions import ALL_WAREHOUSE_ROLES, allows
from app.core.security import decode_token, is_blacklisted
from app.domain.enums import UserStatus
from app.domain.models import User, UserWarehouse

bearer = HTTPBearer(auto_error=False)

DbDep = Annotated[Session, Depends(get_session)]


def get_current_user(
    request: Request,
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: DbDep,
) -> User:
    if cred is None or not cred.credentials:
        raise BizError(Codes.UNAUTHORIZED, "未登录")
    payload = decode_token(cred.credentials)
    jti = payload.get("jti", "")
    if is_blacklisted(jti):
        raise BizError(Codes.UNAUTHORIZED, "登录已失效，请重新登录")
    # 8h 无操作作废：会话键只在活跃请求上续期
    if not _touch_session(jti):
        raise BizError(Codes.UNAUTHORIZED, "长时间未操作，请重新登录")
    user = db.get(User, int(payload["sub"]))
    if user is None or user.status != UserStatus.ENABLED:
        raise BizError(Codes.UNAUTHORIZED, "账号不存在或已停用")
    request.state.user_id = user.id  # 幂等中间件写 op_log 用
    return user


def _touch_session(jti: str) -> bool:
    from app.core.redis import rds

    key = f"sess:{jti}"
    if not rds.exists(key):
        rds.set(key, "1", ex=settings.idle_ttl)
    else:
        rds.expire(key, settings.idle_ttl)
    return True


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(*perms: str):
    """角色守卫：满足任意一个 perm 即放行。"""

    def checker(user: CurrentUser) -> User:
        if not any(allows(user.role, p) for p in perms):
            raise BizError(Codes.FORBIDDEN, "无权限执行该操作")
        return user

    return checker


# 角色守卫别名：在 Annotated 里写死，避免 `x: CurrentUser = Depends(...)` 的冲突写法
AdminUser = Annotated[User, Depends(require("system:manage"))]
BaseDataAdmin = Annotated[User, Depends(require("basedata:manage"))]
BaseDataViewer = Annotated[User, Depends(require("basedata:view"))]
InventoryViewer = Annotated[User, Depends(require("inventory:view"))]
InspectorUser = Annotated[User, Depends(require("inspection:judge"))]
InboundVoidUser = Annotated[User, Depends(require("inbound:void"))]
# 盘点创建/盈亏确认、供应商维护：主管及以上（PRD 3.2）
StocktakeUser = Annotated[User, Depends(require("stocktake:manage"))]
SupplierAdmin = Annotated[User, Depends(require("supplier:manage"))]


def get_warehouse_scope(user: CurrentUser, db: DbDep) -> list[int] | None:
    """返回当前用户可见仓库 id 列表；None 表示不限（主管/管理员/集成账号）。"""
    if user.role in ALL_WAREHOUSE_ROLES:
        return None
    return list(
        db.execute(
            select(UserWarehouse.warehouse_id).where(UserWarehouse.user_id == user.id)
        ).scalars()
    )

WarehouseScope = Annotated[list[int] | None, Depends(get_warehouse_scope)]


def enforce_warehouse(scope: list[int] | None, warehouse_id: int | None) -> None:
    """跨仓越权拦截。scope 为 None 时放行。"""
    if warehouse_id is None or scope is None:
        return
    if int(warehouse_id) not in scope:
        raise BizError(Codes.FORBIDDEN, "无权访问该仓库的数据")
