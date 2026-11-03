"""来料检验服务：列表 / 详情 / 扫码 / 判定 / 生成入库单（接口 11/12/34/35/36，页面 P14/A05）。

判定规则（PRD 5.3）：
  合格          实收 = 计划 且全部合格        → 全量生成入库单
  部分合格      实收 < 计划 或部分不合格       → 按合格数量生成，差异进拒收记录
  合格（超收）  实收 > 计划 且超收 ≤ 阈值      → 自动生成；超出转人工
  不合格        质检不合格                    → 不生成，物料退回

超收阈值：全局默认 5%，供应商档案可覆盖（BR-023，覆盖值优先）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BizError, Codes
from app.domain.enums import InboundType, InspectionStatus, OrderStatus
from app.domain.machine import transit
from app.domain.models import (
    InboundItem,
    InboundOrder,
    Inspection,
    InspectionItem,
    Material,
    Supplier,
)
from app.domain.rules import gen_no
from app.schemas.inbound import (
    GenInboundReq,
    InspectionJudgeReq,
    InspectionScanReq,
)
from app.service.admin_service import get_config

_NOW = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731

DEFAULT_OVER_RECEIVE = "0.05"

RESULT_LABELS = {
    "PASS": "合格",
    "PARTIAL": "部分合格",
    "OVER_PASS": "合格（超收）",
    "FAIL": "不合格",
}

STATUS_LABELS = {
    str(InspectionStatus.PENDING): "待检",
    str(InspectionStatus.CHECKING): "检验中",
    str(InspectionStatus.DONE): "已检",
}


def _s(v) -> str:
    return v.isoformat(sep=" ", timespec="seconds") if v else ""


def over_receive_ratio(db: Session, supplier_id: int) -> Decimal:
    """BR-023：供应商档案的覆盖值优先，否则回落 sys_config 的全局默认。"""
    supplier = db.get(Supplier, supplier_id)
    if supplier is not None and supplier.over_receive is not None:
        return Decimal(str(supplier.over_receive))
    raw = get_config(db, "over_receive_ratio", DEFAULT_OVER_RECEIVE)
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal(DEFAULT_OVER_RECEIVE)


def _dict(db: Session, i: Inspection, with_items: bool = False) -> dict:
    supplier = db.get(Supplier, i.supplier_id)
    d = {
        "id": i.id,
        "no": i.no,
        "supplier_id": i.supplier_id,
        "supplier_name": supplier.name if supplier else None,
        "logistics_no": i.logistics_no,
        "plate_no": i.plate_no,
        "status": i.status,
        "status_label": STATUS_LABELS.get(i.status, i.status),
        "result": i.result,
        "result_label": RESULT_LABELS.get(i.result or "", None),
        "plan_qty": i.plan_qty,
        "actual_qty": i.actual_qty,
        "fail_reason": i.fail_reason,
        "creator_id": i.creator_id,
        "created_at": _s(i.created_at),
        "checked_at": _s(i.checked_at),
        "terminal": i.status == str(InspectionStatus.DONE),
    }
    if with_items:
        rows = db.execute(
            select(InspectionItem, Material.code, Material.name, Material.unit)
            .join(Material, Material.id == InspectionItem.material_id)
            .where(InspectionItem.inspection_id == i.id)
            .order_by(InspectionItem.id)
        ).all()
        d["items"] = [
            {
                "id": it.id,
                "material_id": it.material_id,
                "material_code": code,
                "material_name": name,
                "unit": unit,
                "plan_qty": it.plan_qty,
                "actual_qty": it.actual_qty,
                "barcode": it.barcode,
                "qualified": it.qualified,
            }
            for it, code, name, unit in rows
        ]
        d["over_receive_ratio"] = str(over_receive_ratio(db, i.supplier_id))
    return d


# ---------------------------------------------------------------- 查询
def list_inspections(db: Session, *, q) -> tuple[list[dict], int]:
    stmt = select(Inspection)
    if q.status:
        stmt = stmt.where(Inspection.status == q.status)
    if q.result:
        stmt = stmt.where(Inspection.result == q.result)
    if q.no:
        stmt = stmt.where(Inspection.no.like(f"%{q.no}%"))
    if q.supplier_id:
        stmt = stmt.where(Inspection.supplier_id == q.supplier_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(
        stmt.order_by(Inspection.id.desc())
        .limit(q.page_size)
        .offset((q.page - 1) * q.page_size)
    ).scalars().all()
    return [_dict(db, i) for i in rows], int(total or 0)


def get_inspection(db: Session, inspection_id: int) -> dict:
    i = db.get(Inspection, inspection_id)
    if i is None:
        raise BizError(Codes.BAD_REQUEST, "检验单不存在")
    return _dict(db, i, with_items=True)


# ---------------------------------------------------------------- 扫码
def scan(db: Session, inspection_id: int, req: InspectionScanReq, operator_id: int) -> dict:
    """来料检验扫码：追加明细，累计实收，状态推进到「检验中」（接口 34）。"""
    i = db.get(Inspection, inspection_id)
    if i is None:
        raise BizError(Codes.BAD_REQUEST, "检验单不存在")
    if i.status == str(InspectionStatus.DONE):
        raise BizError(Codes.ORDER_CLOSED, "检验单已判定完成，不能继续扫码")

    material = db.get(Material, req.material_id)
    if material is None:
        raise BizError(Codes.BAD_REQUEST, "物料不存在")

    if i.status == str(InspectionStatus.PENDING):
        i.status = transit("INSPECTION", i.status, str(InspectionStatus.CHECKING))

    item = db.execute(
        select(InspectionItem).where(
            InspectionItem.inspection_id == i.id,
            InspectionItem.material_id == req.material_id,
            InspectionItem.barcode == req.barcode,
        )
    ).scalar_one_or_none()
    if item is None:
        item = InspectionItem(
            inspection_id=i.id, material_id=req.material_id, barcode=req.barcode,
            plan_qty=0, actual_qty=0,
        )
        db.add(item)
    item.actual_qty = (item.actual_qty or 0) + req.actual_qty
    i.actual_qty = (i.actual_qty or 0) + req.actual_qty
    i.version += 1
    db.commit()

    return {
        "inspection_id": i.id,
        "status": i.status,
        "scanned": i.actual_qty,
        "plan_qty": i.plan_qty,
    }


# ---------------------------------------------------------------- 判定
def judge(db: Session, inspection_id: int, req: InspectionJudgeReq, operator_id: int) -> dict:
    """提交判定（接口 35）。不合格必填原因，进供应商质量档案。"""
    i = db.get(Inspection, inspection_id)
    if i is None:
        raise BizError(Codes.BAD_REQUEST, "检验单不存在")
    if i.status == str(InspectionStatus.DONE):
        raise BizError(Codes.ORDER_CLOSED, "检验单已判定，不能重复提交")

    if req.result == "FAIL" and not (req.fail_reason or "").strip():
        raise BizError(Codes.BAD_REQUEST, "判定为不合格必须填写原因")

    # 超收判定：实收 > 计划时校验是否在阈值内
    if req.result == "OVER_PASS":
        ratio = over_receive_ratio(db, i.supplier_id)
        limit = (Decimal(i.plan_qty) * (1 + ratio)).to_integral_value()
        if i.actual_qty > limit:
            raise BizError(
                Codes.BIZ_RULE,
                f"超收 {i.actual_qty - i.plan_qty} 件，超过阈值 "
                f"{ratio * 100:.0f}%（上限 {int(limit)} 件），转主管人工处理",
                data={"over_receive_ratio": str(ratio), "limit": int(limit)},
            )

    # 部分合格：把合格数写回明细，未扫到的行视为不合格
    if req.result in ("PASS", "PARTIAL"):
        _mark_qualified(db, i, qualified=req.result == "PASS")

    i.result = req.result
    i.fail_reason = (req.fail_reason or "").strip() or None
    i.status = transit("INSPECTION", i.status, str(InspectionStatus.DONE))
    i.checked_at = _NOW()
    i.version += 1
    db.commit()

    return {
        "inspection_id": i.id,
        "no": i.no,
        "status": i.status,
        "result": i.result,
        "result_label": RESULT_LABELS.get(i.result, i.result),
    }


def _mark_qualified(db: Session, i: Inspection, *, qualified: bool) -> None:
    rows = db.execute(
        select(InspectionItem).where(InspectionItem.inspection_id == i.id)
    ).scalars().all()
    for r in rows:
        r.qualified = qualified if r.actual_qty else False


# ---------------------------------------------------------------- 生成入库单
def gen_inbound(db: Session, inspection_id: int, req: GenInboundReq, operator_id: int) -> dict:
    """已检合格 → 生成采购入库单（接口 36）。允许一个检验单拆多次入库。

    BR-004：检验未通过不可入库。BR-005：超收默认 5%，超出转主管。
    """
    i = db.get(Inspection, inspection_id)
    if i is None:
        raise BizError(Codes.BAD_REQUEST, "检验单不存在")
    if i.status != str(InspectionStatus.DONE):
        raise BizError(Codes.BIZ_RULE, "检验单尚未判定完成，不能生成入库单")
    if i.result not in ("PASS", "PARTIAL", "OVER_PASS"):
        raise BizError(Codes.BIZ_RULE, f"检验结果为「{RESULT_LABELS.get(i.result, i.result)}」，不能入库")

    # 已生成过的数量要扣掉，避免重复入库
    generated = db.execute(
        select(func.coalesce(func.sum(InboundOrder.plan_qty), 0)).where(
            InboundOrder.source_no == i.no, InboundOrder.type == str(InboundType.PURCHASE)
        )
    ).scalar()
    remain = (i.actual_qty or 0) - int(generated or 0)
    if remain <= 0:
        raise BizError(Codes.BIZ_RULE, f"检验单 {i.no} 的合格数量已全部生成入库单")

    qty = req.qty or remain
    if qty > remain:
        raise BizError(
            Codes.BIZ_RULE,
            f"本次入库 {qty} 超过剩余合格数 {remain}",
            data={"remain": remain},
        )

    # 超收部分仍需人工确认（BR-005）
    ratio = over_receive_ratio(db, i.supplier_id)
    total_after = int(generated or 0) + qty
    limit = int((Decimal(i.plan_qty) * (1 + ratio)).to_integral_value())
    if total_after > limit and i.result != "OVER_PASS":
        raise BizError(
            Codes.BIZ_RULE,
            f"累计入库 {total_after} 超过阈值上限 {limit}（超收 {ratio * 100:.0f}%），转主管处理",
        )

    material_id = db.execute(
        select(InspectionItem.material_id)
        .where(InspectionItem.inspection_id == i.id, InspectionItem.qualified.is_(True))
        .limit(1)
    ).scalar()
    if material_id is None:
        raise BizError(Codes.BIZ_RULE, "检验单没有合格明细，不能生成入库单")

    order = InboundOrder(
        no=gen_no("PR"),
        type=str(InboundType.PURCHASE),
        source_no=i.no,
        supplier_id=i.supplier_id,
        status=str(OrderStatus.PENDING),
        plan_qty=qty,
        actual_qty=0,
        creator_id=operator_id,
        config_snapshot={"over_receive_ratio": str(ratio)},
    )
    db.add(order)
    db.flush()
    db.add(InboundItem(order_id=order.id, sku_id=material_id, qty=0, location_id=req.location_id))
    db.commit()

    return {
        "order_id": order.id,
        "no": order.no,
        "type": order.type,
        "plan_qty": order.plan_qty,
        "remain": remain - qty,
    }
