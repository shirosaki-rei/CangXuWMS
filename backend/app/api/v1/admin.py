"""账号与权限接口（接口文档 22–24、48–51）。仅系统管理员。"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.core.deps import AdminUser, DbDep
from app.core.errors import ok
from app.schemas.basedata import SysConfigIn, UserIn, UserRolesIn, UserUpdate
from app.service import admin_service as svc

router = APIRouter(tags=["账号与权限"])

@router.get("/users", summary="账号列表（接口 22）")
def list_users(request: Request, db: DbDep, _user: AdminUser,
               role: str | None = Query(None), status: str | None = Query(None),
               keyword: str | None = Query(None)) -> dict:
    return ok(svc.list_users(db, role=role, status=status, keyword=keyword),
              trace_id=request.state.trace_id)


@router.post("/users", summary="新增账号（接口 48）")
def create_user(request: Request, db: DbDep, body: UserIn,
                _user: AdminUser) -> dict:
    return ok({"id": svc.create_user(db, body)}, trace_id=request.state.trace_id)


@router.put("/users/{uid}", summary="编辑账号/重置密码/停用（接口 49）")
def update_user(request: Request, db: DbDep, uid: int, body: UserUpdate,
                _user: AdminUser) -> dict:
    svc.update_user(db, uid, body)
    return ok({"ok": True}, trace_id=request.state.trace_id)


@router.post("/users/{uid}/roles", summary="分配角色与数据权限（接口 50）")
def assign_roles(request: Request, db: DbDep, uid: int, body: UserRolesIn,
                 _user: AdminUser) -> dict:
    svc.assign_roles(db, uid, body)
    return ok({"ok": True}, trace_id=request.state.trace_id)


@router.get("/roles", summary="角色清单（接口 23）")
def list_roles(request: Request, db: DbDep, _user: AdminUser) -> dict:
    return ok(svc.list_roles(db), trace_id=request.state.trace_id)


@router.get("/permission-matrix", summary="权限矩阵（PRD 3.2）")
def matrix(request: Request, db: DbDep, _user: AdminUser) -> dict:
    return ok(svc.permission_matrix(), trace_id=request.state.trace_id)


@router.get("/sys-configs", summary="规则配置列表（接口 24）")
def list_configs(request: Request, db: DbDep, _user: AdminUser,
                 scope: str | None = Query(None)) -> dict:
    return ok(svc.list_sys_configs(db, scope=scope), trace_id=request.state.trace_id)


@router.put("/sys-configs", summary="修改规则配置（接口 51，BR-026 只对新建单生效）")
def upsert_config(request: Request, db: DbDep, body: SysConfigIn,
                  user: AdminUser) -> dict:
    svc.upsert_sys_config(db, body, user.id)
    return ok({"ok": True}, trace_id=request.state.trace_id)
