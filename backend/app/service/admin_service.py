"""账号与权限服务：用户 / 角色 / 数据权限 / 规则配置（接口 22–24、48–51）。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import BizError, Codes
from app.core.permissions import MATRIX, ROLE_LABELS
from app.core.security import hash_password
from app.domain.models import SysConfig, User, UserWarehouse, Warehouse
from app.domain.rules import mask_phone
from app.schemas.basedata import SysConfigIn, UserIn, UserRolesIn, UserUpdate

_NOW = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731


def _s(v) -> str:
    return v.isoformat(sep=" ", timespec="seconds") if v else ""


def _wh_ids(db: Session, user_id: int) -> list[int]:
    return list(
        db.execute(
            select(UserWarehouse.warehouse_id).where(UserWarehouse.user_id == user_id)
        ).scalars()
    )


def list_users(db: Session, *, role: str | None, status: str | None, keyword: str | None):
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if status:
        stmt = stmt.where(User.status == status)
    if keyword:
        stmt = stmt.where((User.name.like(f"%{keyword}%")) | (User.username.like(f"%{keyword}%")))
    rows = db.execute(stmt.order_by(User.id.desc())).scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "name": u.name,
            "phone": mask_phone(u.phone),
            "role": u.role,
            "role_label": ROLE_LABELS.get(u.role, u.role),
            "status": u.status,
            "warehouse_ids": _wh_ids(db, u.id),
            "created_at": _s(u.created_at),
        }
        for u in rows
    ]


def create_user(db: Session, data: UserIn) -> int:
    if db.execute(select(User.id).where(User.username == data.username)).first():
        raise BizError(Codes.DUPLICATE, f"账号 {data.username} 已存在")
    u = User(
        username=data.username,
        name=data.name,
        phone=data.phone,
        role=str(data.role),
        password=hash_password(data.password),
    )
    db.add(u)
    db.commit()
    return u.id


def update_user(db: Session, uid: int, data: UserUpdate) -> None:
    u = db.get(User, uid)
    if u is None:
        raise BizError(Codes.BAD_REQUEST, "账号不存在")
    if data.name is not None:
        u.name = data.name
    if data.phone is not None:
        u.phone = data.phone
    if data.status is not None:
        u.status = str(data.status)
    if data.password:
        u.password = hash_password(data.password)
        u.fail_count = 0
        u.locked_until = None
    db.commit()


def assign_roles(db: Session, uid: int, data: UserRolesIn) -> None:
    """改角色与数据权限。仓管员/检验员必须至少分配一个仓库，否则登录后看不到任何数据。"""
    u = db.get(User, uid)
    if u is None:
        raise BizError(Codes.BAD_REQUEST, "账号不存在")
    u.role = str(data.role)
    if u.role not in ("SUPERVISOR", "ADMIN", "INTEGRATION") and not data.warehouse_ids:
        raise BizError(Codes.BAD_REQUEST, "该角色必须至少分配一个可见仓库")

    ids = list(dict.fromkeys(data.warehouse_ids))
    found = set(db.execute(select(Warehouse.id).where(Warehouse.id.in_(ids))).scalars())
    missing = set(ids) - found
    if missing:
        raise BizError(Codes.BAD_REQUEST, f"仓库不存在：{sorted(missing)}")

    db.execute(delete(UserWarehouse).where(UserWarehouse.user_id == uid))
    db.add_all([UserWarehouse(user_id=uid, warehouse_id=i) for i in sorted(found)])
    db.commit()


def list_roles(db: Session) -> list[dict]:
    out = []
    for value, label in ROLE_LABELS.items():
        perms = sorted(k for k, roles in MATRIX.items() if value in roles)
        out.append({"value": value, "label": label, "permissions": perms})
    return out


def permission_matrix() -> dict:
    """PRD 3.2 的 14 行矩阵，前端权限矩阵页直接渲染。"""
    from app.core.permissions import MATRIX_ROWS

    return {"rows": MATRIX_ROWS, "roles": list(ROLE_LABELS.items())}


# ---------------------------------------------------------------- 规则配置
def list_sys_configs(db: Session, *, scope: str | None = None):
    stmt = select(SysConfig)
    if scope:
        stmt = stmt.where(SysConfig.scope == scope)
    rows = db.execute(stmt.order_by(SysConfig.cfg_key)).scalars().all()
    return [
        {
            "id": c.id,
            "cfg_key": c.cfg_key,
            "cfg_value": c.cfg_value,
            "value_type": c.value_type,
            "scope": c.scope,
            "scope_id": c.scope_id,
            "remark": c.remark,
            "updated_at": _s(c.updated_at),
        }
        for c in rows
    ]


def upsert_sys_config(db: Session, data: SysConfigIn, operator_id: int) -> None:
    """BR-026：只对新建单据生效——写入不碰在途单据，service 读配置时才取快照。"""
    if data.scope == "SUPPLIER" and data.scope_id is None:
        raise BizError(Codes.BAD_REQUEST, "scope=SUPPLIER 时必须填 scope_id")
    row = db.execute(
        select(SysConfig).where(
            SysConfig.cfg_key == data.cfg_key,
            SysConfig.scope == data.scope,
            SysConfig.scope_id == data.scope_id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = SysConfig(cfg_key=data.cfg_key, scope=data.scope, scope_id=data.scope_id)
        db.add(row)
    row.cfg_value = data.cfg_value
    row.value_type = data.value_type
    row.remark = data.remark
    row.updated_by = operator_id
    db.commit()


def get_config(db: Session, key: str, default=None, *, scope_id: int | None = None):
    """读配置：SUPPLIER 级命中优先，否则回落 GLOBAL（架构 6.2）。"""
    if scope_id is not None:
        row = db.execute(
            select(SysConfig.cfg_value).where(
                SysConfig.cfg_key == key,
                SysConfig.scope == "SUPPLIER",
                SysConfig.scope_id == scope_id,
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
    return db.execute(
        select(SysConfig.cfg_value).where(
            SysConfig.cfg_key == key, SysConfig.scope == "GLOBAL"
        )
    ).scalar_one_or_none() or default
