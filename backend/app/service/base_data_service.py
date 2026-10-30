"""基础资料服务：仓库 / 库位 / 条码（P18–P20，接口 18–20、39–46）。

涉及规则：BR-009 条码全局唯一、BR-013 危品库位只放危品、BR-014 停用仓库前校验、
BR-025 坐标缺失标记、BR-008 库位状态自动流转。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BizError, Codes
from app.domain.enums import LocationStatus, Switch
from app.domain.models import (
    Barcode,
    InboundOrder,
    Inventory,
    Location,
    OutboundOrder,
    Warehouse,
)
from app.domain.rules import assert_warehouse_disable_ok, location_status_after
from app.schemas.basedata import (
    BarcodeIn,
    LocationIn,
    LocationStatusIn,
    WarehouseIn,
)

_NOW = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731


def _s(v) -> str:
    return v.isoformat(sep=" ", timespec="seconds") if v else ""


# ---------------------------------------------------------------- 仓库
def list_warehouses(
    db: Session,
    *,
    name: str | None,
    wtype: str | None,
    status: str | None,
    scope: list[int] | None = None,
):
    """scope 为 None 表示不限（主管/管理员/集成账号）；否则只列被分配的仓库。"""
    stmt = select(Warehouse)
    if scope is not None:
        if not scope:
            return []
        stmt = stmt.where(Warehouse.id.in_(scope))
    if name:
        stmt = stmt.where(Warehouse.name.like(f"%{name}%"))
    if wtype:
        stmt = stmt.where(Warehouse.type == wtype)
    if status:
        stmt = stmt.where(Warehouse.status == status)
    rows = db.execute(stmt.order_by(Warehouse.id.desc())).scalars().all()
    counts = dict(
        db.execute(
            select(Location.warehouse_id, func.count())
            .where(Location.status != "MAINTAIN")
            .group_by(Location.warehouse_id)
        ).all()
    )
    return [
        {
            "id": w.id,
            "code": w.code,
            "name": w.name,
            "type": w.type,
            "status": w.status,
            "owner_id": w.owner_id,
            "location_count": int(counts.get(w.id, 0)),
            "created_at": _s(w.created_at),
        }
        for w in rows
    ]


def create_warehouse(db: Session, data: WarehouseIn) -> int:
    if db.execute(select(Warehouse.id).where(Warehouse.code == data.code)).first():
        raise BizError(Codes.DUPLICATE, f"仓库编码 {data.code} 已存在")
    w = Warehouse(**data.model_dump())
    db.add(w)
    db.commit()
    return w.id


def update_warehouse(db: Session, wid: int, data: WarehouseIn) -> None:
    w = db.get(Warehouse, wid)
    if w is None:
        raise BizError(Codes.BAD_REQUEST, "仓库不存在")
    if w.code != data.code and db.execute(
        select(Warehouse.id).where(Warehouse.code == data.code, Warehouse.id != wid)
    ).first():
        raise BizError(Codes.DUPLICATE, f"仓库编码 {data.code} 已存在")
    for k, v in data.model_dump().items():
        setattr(w, k, v)
    db.commit()


def toggle_warehouse(db: Session, wid: int, status: str) -> None:
    """BR-014：停用前校验库存为 0 且无未结单据，否则拒绝并列出阻塞项。"""
    w = db.get(Warehouse, wid)
    if w is None:
        raise BizError(Codes.BAD_REQUEST, "仓库不存在")
    if status == Switch.DISABLED:
        assert_warehouse_disable_ok(location_blockers(db, wid))
    w.status = status
    db.commit()


# ---------------------------------------------------------------- 库位
def list_locations(
    db: Session,
    *,
    warehouse_id: int | None,
    ltype: str | None,
    status: str | None,
    code: str | None = None,
    scope: list[int] | None = None,
):
    """scope 为 None 表示不限；否则只列被分配仓库下的库位。"""
    stmt = select(Location, Warehouse.name).join(Warehouse, Warehouse.id == Location.warehouse_id)
    if scope is not None:
        if not scope:
            return []
        stmt = stmt.where(Location.warehouse_id.in_(scope))
    if warehouse_id:
        stmt = stmt.where(Location.warehouse_id == warehouse_id)
    if ltype:
        stmt = stmt.where(Location.type == ltype)
    if status:
        stmt = stmt.where(Location.status == status)
    if code:
        stmt = stmt.where(Location.code.like(f"%{code}%"))
    rows = db.execute(stmt.order_by(Location.id.desc())).all()
    return [
        {
            "id": loc.id,
            "code": loc.code,
            "name": loc.name,
            "type": loc.type,
            "warehouse_id": loc.warehouse_id,
            "warehouse_name": wname,
            "cap_pallet": loc.cap_pallet,
            "cap_material": loc.cap_material,
            "used_pallet": loc.used_pallet,
            "status": loc.status,
            "coord_x": float(loc.coord_x) if loc.coord_x is not None else None,
            "coord_y": float(loc.coord_y) if loc.coord_y is not None else None,
            "coord_missing": loc.coord_x is None or loc.coord_y is None,  # BR-025
            "created_at": _s(loc.created_at),
        }
        for loc, wname in rows
    ]


def create_location(db: Session, data: LocationIn) -> int:
    if db.execute(select(Location.id).where(Location.code == data.code)).first():
        raise BizError(Codes.DUPLICATE, f"库位编码 {data.code} 已存在")
    if db.get(Warehouse, data.warehouse_id) is None:
        raise BizError(Codes.BAD_REQUEST, "所属仓库不存在")
    loc = Location(**data.model_dump(), status=LocationStatus.IDLE)
    db.add(loc)
    db.commit()
    return loc.id


def update_location(db: Session, lid: int, data: LocationIn) -> None:
    loc = db.get(Location, lid)
    if loc is None:
        raise BizError(Codes.BAD_REQUEST, "库位不存在")
    if loc.code != data.code and db.execute(
        select(Location.id).where(Location.code == data.code, Location.id != lid)
    ).first():
        raise BizError(Codes.DUPLICATE, f"库位编码 {data.code} 已存在")
    if db.get(Warehouse, data.warehouse_id) is None:
        raise BizError(Codes.BAD_REQUEST, "所属仓库不存在")
    for k, v in data.model_dump().items():
        setattr(loc, k, v)
    db.commit()


def set_location_status(db: Session, lid: int, status: str) -> None:
    """BR-008：人工只能设「锁定」「维保」；解锁走 IDLE/OCCUPIED 自动推导。"""
    loc = db.get(Location, lid)
    if loc is None:
        raise BizError(Codes.BAD_REQUEST, "库位不存在")
    if status not in (LocationStatus.LOCKED, LocationStatus.MAINTAIN):
        raise BizError(Codes.BIZ_RULE, "人工只能设置「锁定」或「维保」，其余状态由系统按库存自动流转")
    if status == LocationStatus.LOCKED:
        qty = db.execute(
            select(func.coalesce(func.sum(Inventory.qty), 0)).where(Inventory.location_id == lid)
        ).scalar()
        if qty:
            raise BizError(Codes.BIZ_RULE, f"库位仍有库存 {int(qty)} 件，不能锁定")
    loc.status = status
    db.commit()


# ---------------------------------------------------------------- 条码
def list_barcodes(db: Session, *, btype: str | None, code: str | None = None):
    stmt = select(Barcode)
    if btype:
        stmt = stmt.where(Barcode.type == btype)
    if code:
        stmt = stmt.where(Barcode.code.like(f"%{code}%"))
    rows = db.execute(stmt.order_by(Barcode.id.desc())).scalars().all()
    return [
        {
            "id": b.id,
            "code": b.code,
            "type": b.type,
            "ref_id": b.ref_id,
            "created_at": _s(b.created_at),
        }
        for b in rows
    ]


def create_barcode(db: Session, data: BarcodeIn) -> int:
    """BR-009：条码全局唯一，重复生成校验失败。"""
    if db.execute(select(Barcode.id).where(Barcode.code == data.code)).first():
        raise BizError(Codes.DUPLICATE, f"条码 {data.code} 已存在（BR-009 全局唯一）")
    b = Barcode(**data.model_dump())
    db.add(b)
    db.commit()
    return b.id


def print_barcodes(db: Session, ids: list[int], spec: str, copies: int) -> dict:
    """I-03：服务端生成 PDF 与浏览器直连打印机两端都留口，这里先返回待打印清单。"""
    rows = db.execute(select(Barcode).where(Barcode.id.in_(ids))).scalars().all()
    if not rows:
        raise BizError(Codes.BAD_REQUEST, "没有选中的条码")
    return {
        "spec": spec,
        "copies": copies,
        "total": len(rows) * copies,
        "items": [{"code": b.code, "type": b.type} for b in rows],
        # ponytail: 真 PDF 生成（reportlab）等 B03 有打印机联调时再加，先返回结构化数据
        "pdf_url": None,
    }


def location_blockers(db: Session, warehouse_id: int) -> list[str]:
    """停用仓库时的阻塞项清单，前端直接展示。"""
    blockers: list[str] = []
    qty = db.execute(
        select(func.coalesce(func.sum(Inventory.qty), 0))
        .join(Location, Location.id == Inventory.location_id)
        .where(Location.warehouse_id == warehouse_id)
    ).scalar()
    if qty:
        blockers.append(f"仓内仍有库存 {int(qty)} 件")
    open_in = int(
        db.execute(
            select(func.count()).select_from(InboundOrder).where(InboundOrder.status.in_(("PENDING", "PARTIAL")))
        ).scalar()
    )
    open_out = int(
        db.execute(
            select(func.count()).select_from(OutboundOrder).where(OutboundOrder.status.in_(("PENDING", "PARTIAL")))
        ).scalar()
    )
    if open_in or open_out:
        blockers.append(f"未结入库单 {open_in} 张、未结出库单 {open_out} 张")
    return blockers
