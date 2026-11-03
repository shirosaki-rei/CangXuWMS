"""移位服务（接口 16/17/33，页面 P17 / APP A09）。

移位不改总量，只改库位维度（PRD 6.6.4）。APP 侧是「扫源库位 → 扫物料 → 扫目标库位」
三扫，服务端只校验最终状态是否允许这次搬动。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BizError, Codes
from app.domain.enums import BizType, LocationStatus, MoveStatus, SkuType
from app.domain.machine import transit
from app.domain.models import Inventory, Location, Material, MoveOrder
from app.domain.rules import gen_no, location_mismatch_reason, location_status_after
from app.domain.stock import Move, apply_many
from app.schemas.stocktake import MoveCreateReq

_NOW = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731

_LOC_CN = {
    str(LocationStatus.IDLE): "空闲",
    str(LocationStatus.OCCUPIED): "占用",
    str(LocationStatus.LOCKED): "锁定",
    str(LocationStatus.MAINTAIN): "维保",
}


def _status_cn(s: str) -> str:
    return _LOC_CN.get(s, s)


STATUS_LABELS = {
    str(MoveStatus.PENDING): "待执行",
    str(MoveStatus.DOING): "执行中",
    str(MoveStatus.DONE): "已完成",
}


def _s(v) -> str:
    return v.isoformat(sep=" ", timespec="seconds") if v else ""


def _qty_at(db: Session, material_id: int, location_id: int) -> int:
    return int(db.execute(
        select(func.coalesce(func.sum(Inventory.qty), 0)).where(
            Inventory.sku_type == str(SkuType.MATERIAL),
            Inventory.sku_id == material_id,
            Inventory.location_id == location_id,
        )
    ).scalar())


def create(db: Session, body: MoveCreateReq, operator_id: int) -> dict:
    material = db.get(Material, body.material_id)
    if material is None:
        raise BizError(Codes.BAD_REQUEST, "物料不存在")
    if body.from_location_id == body.to_location_id:
        raise BizError(Codes.BAD_REQUEST, "移入库位不能与移出库位相同")

    src = db.get(Location, body.from_location_id)
    dst = db.get(Location, body.to_location_id)
    if src is None or dst is None:
        raise BizError(Codes.BAD_REQUEST, "库位不存在")
    if src.warehouse_id != dst.warehouse_id:
        raise BizError(Codes.BIZ_RULE, "跨仓库移位不支持，请走调拨流程")
    if dst.status in (LocationStatus.LOCKED, LocationStatus.MAINTAIN):
        raise BizError(Codes.BIZ_RULE, f"目标库位 {dst.code} 处于「{_status_cn(dst.status)}」状态，不能移入")
    if src.status in (LocationStatus.LOCKED, LocationStatus.MAINTAIN):
        raise BizError(Codes.BIZ_RULE, f"源库位 {src.code} 处于「{_status_cn(src.status)}」状态，不能移出")

    # BR-013：危品/恒温库位的属性匹配
    reason = location_mismatch_reason(dst.type, material.is_dangerous, material.temp_control)
    if reason:
        raise BizError(Codes.BIZ_RULE, reason)

    # 可用量
    inv = db.execute(
        select(Inventory).where(
            Inventory.sku_type == str(SkuType.MATERIAL),
            Inventory.sku_id == body.material_id,
            Inventory.location_id == src.id,
        )
    ).scalar_one_or_none()
    available = (inv.qty - inv.locked_qty - inv.frozen_qty) if inv else 0
    if available < body.qty:
        raise BizError(Codes.STOCK_SHORT, f"源库位可用库存不足，缺口 {body.qty - available}",
                       data={"available": available})

    # 目标容量（cap_material 为 0 表示不限）
    if dst.cap_material > 0:
        used = _qty_at(db, body.material_id, dst.id)
        if used + body.qty > dst.cap_material:
            raise BizError(
                Codes.BIZ_RULE,
                f"目标库位剩余容量不足，最多还能放 {max(0, dst.cap_material - used)}",
                data={"remain_capacity": max(0, dst.cap_material - used)},
            )

    order = MoveOrder(
        no=gen_no("YK"),
        material_id=body.material_id,
        from_loc_id=src.id,
        to_loc_id=dst.id,
        qty=body.qty,
        status=str(MoveStatus.PENDING),
        operator_id=operator_id,
    )
    db.add(order)
    db.flush()

    # 源库位临时锁定（PRD 6.6.4）。整笔在同一事务里完成，
    # 真正防并发的是 inventory 行锁；状态锁定只是让界面上的语义对齐。
    order.status = transit("MOVE", order.status, str(MoveStatus.DOING))
    src.status = str(LocationStatus.LOCKED)

    apply_many(
        db,
        [
            Move(str(SkuType.MATERIAL), body.material_id, src.id, -body.qty),
            Move(str(SkuType.MATERIAL), body.material_id, dst.id, body.qty),
        ],
        biz_type=str(BizType.MOVE), biz_no=order.no, operator_id=operator_id,
    )
    db.flush()

    # 还原库位状态：源库位按剩余库存推，目标库位按现有库存推
    src_qty = _qty_at(db, body.material_id, src.id)
    src.status = location_status_after(str(LocationStatus.IDLE), src_qty)
    dst_total = db.execute(
        select(func.coalesce(func.sum(Inventory.qty), 0)).where(Inventory.location_id == dst.id)
    ).scalar()
    if dst.status not in (LocationStatus.LOCKED, LocationStatus.MAINTAIN):
        dst.status = location_status_after(str(LocationStatus.IDLE), int(dst_total))

    order.status = transit("MOVE", order.status, str(MoveStatus.DONE))
    order.finished_at = _NOW()
    db.commit()

    return {
        "id": order.id,
        "no": order.no,
        "status": order.status,
        "from_location": src.code,
        "to_location": dst.code,
        "qty": order.qty,
        "source_remain": src_qty,
    }


def list_moves(db: Session, *, q) -> tuple[list[dict], int]:
    stmt = select(MoveOrder)
    if q.no:
        stmt = stmt.where(MoveOrder.no.like(f"%{q.no}%"))
    if q.material_id:
        stmt = stmt.where(MoveOrder.material_id == q.material_id)
    if q.status:
        stmt = stmt.where(MoveOrder.status == q.status)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(
        stmt.order_by(MoveOrder.id.desc()).limit(q.page_size).offset((q.page - 1) * q.page_size)
    ).scalars().all()
    return [_dict(db, m) for m in rows], int(total or 0)


def get_move(db: Session, mid: int) -> dict:
    m = db.get(MoveOrder, mid)
    if m is None:
        raise BizError(Codes.BAD_REQUEST, "移位单不存在")
    return _dict(db, m)


def _dict(db: Session, m: MoveOrder) -> dict:
    mat = db.get(Material, m.material_id)
    src = db.get(Location, m.from_loc_id)
    dst = db.get(Location, m.to_loc_id)
    return {
        "id": m.id,
        "no": m.no,
        "material_id": m.material_id,
        "material_code": mat.code if mat else None,
        "material_name": mat.name if mat else None,
        "unit": mat.unit if mat else None,
        "from_location_id": m.from_loc_id,
        "from_location_code": src.code if src else None,
        "to_location_id": m.to_loc_id,
        "to_location_code": dst.code if dst else None,
        "qty": m.qty,
        "status": m.status,
        "status_label": STATUS_LABELS.get(m.status, m.status),
        "operator_id": m.operator_id,
        "created_at": _s(m.created_at),
        "finished_at": _s(m.finished_at),
    }
