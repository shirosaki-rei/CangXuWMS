"""出库单服务：列表 / 详情 / FIFO 推荐 / 扫码拣货 / 提交 / 作废
（接口 9/10/28/29/38，页面 P10–P13）。

涉及规则：
  BR-003 出库默认 FIFO：按入库完成时间升序，同时间按库位编码升序
  BR-010 同一 SN 不可同时存在于两张未关闭的单据
  BR-011 终态不可回退，作废需原因并留痕
  BR-001/002 库存只能被单据改变、流水只增不改
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BizError, Codes
from app.domain.enums import BizType, LocationStatus, OrderStatus, OutboundType, SkuType
from app.domain.machine import advance_by_qty, is_terminal, transit
from app.domain.models import (
    Inventory,
    Location,
    Material,
    OutboundItem,
    OutboundOrder,
    Product,
    Txn,
)
from app.domain.stock import Move, apply_many
from app.schemas.outbound import OutboundSubmitReq, OutboundVoidReq, PickReq

_NOW = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731

# 出库单类型 → SKU 类型。销售出成品，领料/盘亏出物料。
_SKU_TYPE = {
    str(OutboundType.SALES): str(SkuType.PRODUCT),
    str(OutboundType.PICK): str(SkuType.MATERIAL),
    str(OutboundType.LOSS): str(SkuType.MATERIAL),
}

_BIZ_TYPE = {
    str(OutboundType.SALES): BizType.SALES_OUT,
    str(OutboundType.PICK): BizType.PICK_OUT,
    str(OutboundType.LOSS): BizType.LOSS_OUT,
}

TYPE_LABELS = {
    str(OutboundType.SALES): "销售出库",
    str(OutboundType.PICK): "领料出库",
    str(OutboundType.LOSS): "盘亏出库",
}

STATUS_LABELS = {
    str(OrderStatus.PENDING): "待出库",
    str(OrderStatus.PARTIAL): "部分出库",
    str(OrderStatus.DONE): "已出库",
    str(OrderStatus.VOID): "已作废",
}


def sku_type_of(order_type: str) -> str:
    return _SKU_TYPE.get(order_type, str(SkuType.MATERIAL))


def _s(v) -> str:
    return v.isoformat(sep=" ", timespec="seconds") if v else ""


def _item_dict(it: OutboundItem) -> dict:
    return {
        "id": it.id,
        "sku_id": it.sku_id,
        "sn": it.sn,
        "location_id": it.location_id,
        "status": it.status,
        "operator_id": it.operator_id,
        "operated_at": _s(it.operated_at),
    }


def _order_dict(o: OutboundOrder, with_items: bool = False) -> dict:
    d = {
        "id": o.id,
        "no": o.no,
        "type": o.type,
        "type_label": TYPE_LABELS.get(o.type, o.type),
        "source_no": o.source_no,
        "status": o.status,
        "status_label": STATUS_LABELS.get(o.status, o.status),
        "plan_qty": o.plan_qty,
        "actual_qty": o.actual_qty,
        "creator_id": o.creator_id,
        "created_at": _s(o.created_at),
        "finished_at": _s(o.finished_at),
        "version": o.version,
        "terminal": is_terminal("OUTBOUND", o.status),
    }
    if with_items:
        d["items"] = []
    return d


# ---------------------------------------------------------------- FIFO 推荐
def fifo_locations(db: Session, sku_type: str, sku_id: int,
                   *, scope: list[int] | None = None) -> list[dict]:
    """BR-003：按入库完成时间升序，同时间按库位编码升序，返回有可用库存的库位。

    「入库完成时间」取该 (sku, location) 最早一条入库流水的时间——库存是流动的，
    用最早入库时间来近似批次先后。
    """
    stmt = (
        select(Inventory, Location.code, Location.status,
               func.min(Txn.created_at).label("first_in"))
        .join(Location, Location.id == Inventory.location_id)
        .outerjoin(
            Txn,
            (Txn.sku_type == Inventory.sku_type)
            & (Txn.sku_id == Inventory.sku_id)
            & (Txn.location_id == Inventory.location_id)
            & (Txn.qty_delta > 0),
        )
        .where(Inventory.sku_type == sku_type, Inventory.sku_id == sku_id)
        .group_by(Inventory.id, Location.code, Location.status)
    )
    if scope is not None:
        if not scope:
            return []
        stmt = stmt.where(Location.warehouse_id.in_(scope))

    rows = db.execute(stmt).all()
    out = []
    for inv, loc_code, loc_status, first_in in rows:
        available = inv.qty - inv.locked_qty - inv.frozen_qty
        if available <= 0:
            continue
        if loc_status == str(LocationStatus.LOCKED):
            continue
        out.append(
            {
                "location_id": inv.location_id,
                "location_code": loc_code,
                "available": available,
                "first_in_at": _s(first_in),
                # 没有入库流水的（种子数据/手工调账）排最后
                "sort_key": (first_in or datetime.max, loc_code),
            }
        )
    out.sort(key=lambda x: x["sort_key"])
    for r in out:
        r.pop("sort_key")
    return out


def recommend(db: Session, sku_type: str, sku_id: int, qty: int,
              *, scope: list[int] | None = None) -> dict:
    """按 FIFO 排出足够 qty 的库位序列；不够时返回缺口。"""
    locs = fifo_locations(db, sku_type, sku_id, scope=scope)
    plan, need = [], qty
    for loc in locs:
        if need <= 0:
            break
        take = min(need, loc["available"])
        plan.append({**loc, "take_qty": take})
        need -= take
    return {
        "sku_id": sku_id,
        "sku_type": sku_type,
        "plan_qty": qty,
        "shortage": need,
        "locations": plan,
        "fifo": True,
    }


# ---------------------------------------------------------------- 查询
def list_orders(db: Session, *, scope: list[int] | None, q) -> tuple[list[dict], int]:
    stmt = select(OutboundOrder)
    if q.type:
        stmt = stmt.where(OutboundOrder.type == q.type)
    if q.status:
        stmt = stmt.where(OutboundOrder.status == q.status)
    if q.no:
        stmt = stmt.where(OutboundOrder.no.like(f"%{q.no}%"))
    if q.source_no:
        stmt = stmt.where(OutboundOrder.source_no.like(f"%{q.source_no}%"))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(
        stmt.order_by(OutboundOrder.id.desc())
        .limit(q.page_size)
        .offset((q.page - 1) * q.page_size)
    ).scalars().all()
    return [_order_dict(o) for o in rows], int(total or 0)


def get_order(db: Session, order_id: int) -> dict:
    o = db.get(OutboundOrder, order_id)
    if o is None:
        raise BizError(Codes.BAD_REQUEST, "出库单不存在")
    d = _order_dict(o, with_items=True)

    items = db.execute(
        select(OutboundItem).where(OutboundItem.order_id == o.id).order_by(OutboundItem.id)
    ).scalars().all()
    d["items"] = [_item_dict(i) for i in items]

    loc_ids = {i.location_id for i in items if i.location_id}
    sku_ids = {i.sku_id for i in items}
    locs = {
        r[0]: r[1]
        for r in db.execute(select(Location.id, Location.code).where(Location.id.in_(loc_ids)))
    } if loc_ids else {}
    sku_table = Product if sku_type_of(o.type) == str(SkuType.PRODUCT) else Material
    skus = {
        r[0]: r[1]
        for r in db.execute(select(sku_table.id, sku_table.code).where(sku_table.id.in_(sku_ids)))
    } if sku_ids else {}
    for it in d["items"]:
        it["location_code"] = locs.get(it["location_id"])
        it["sku_code"] = skus.get(it["sku_id"])
    # 待出库的行不允许有出库人/时间（PRD 6.5.4）
    d["row_violations"] = [
        i["id"] for i in d["items"]
        if i["status"] == "PENDING" and (i["operator_id"] or i["operated_at"])
    ]
    return d


# ---------------------------------------------------------------- 扫码拣货
def pick(db: Session, order_id: int, req: PickReq, operator_id: int) -> dict:
    """扫码拣货：SN 查重 → 库位可用量校验 → 追加明细 → 推进状态（接口 28）。"""
    o = db.get(OutboundOrder, order_id)
    if o is None:
        raise BizError(Codes.BAD_REQUEST, "出库单不存在")
    if is_terminal("OUTBOUND", o.status):
        raise BizError(Codes.ORDER_CLOSED, f"出库单已终态（{o.status}），不能继续拣货")

    sku_type = sku_type_of(o.type)
    first = db.execute(
        select(OutboundItem).where(OutboundItem.order_id == o.id).order_by(OutboundItem.id)
    ).scalars().first()
    sku_id = first.sku_id if first else _sku_from_order(db, o)
    if sku_id is None:
        raise BizError(Codes.BIZ_RULE, "出库单没有可出账的 SKU，请先关联来源单据")

    # BR-010：同一 SN 不能挂在两张未关闭的出库单上
    if req.sn:
        clash = db.execute(
            select(OutboundItem.id, OutboundItem.order_id)
            .join(OutboundOrder, OutboundOrder.id == OutboundItem.order_id)
            .where(
                OutboundItem.sn == req.sn,
                OutboundItem.order_id != order_id,
                OutboundOrder.status.in_((str(OrderStatus.PENDING), str(OrderStatus.PARTIAL))),
            )
        ).first()
        if clash:
            raise BizError(
                Codes.DUPLICATE,
                f"SN {req.sn} 已存在于未关闭的出库单 #{clash[1]}（BR-010）",
                data={"sn": req.sn, "duplicate": True},
            )

    # R5 前置：库位可用量必须够（真正的扣减在 submit，这里先挡一道）
    inv = db.execute(
        select(Inventory).where(
            Inventory.sku_type == sku_type,
            Inventory.sku_id == sku_id,
            Inventory.location_id == req.location_id,
        )
    ).scalar_one_or_none()
    available = (inv.qty - inv.locked_qty - inv.frozen_qty) if inv else 0
    if available < req.qty:
        raise BizError(
            Codes.STOCK_SHORT,
            f"库位可用库存不足，缺口 {req.qty - available}",
            data={"available": available, "shortage": req.qty - available},
        )

    loc = db.get(Location, req.location_id)
    if loc is None:
        raise BizError(Codes.BAD_REQUEST, "库位不存在")

    # outbound_item 没有 qty 列（架构 6.2）：一行一件，逐件 SN 作为发货凭证。
    # 带 SN 时只能一件一扫；不带 SN 才允许批量拣。
    if req.sn and req.qty != 1:
        raise BizError(Codes.BAD_REQUEST, "带 SN 的拣货必须一件一扫（qty 只能为 1）")
    now = _NOW()
    for _ in range(req.qty):
        db.add(OutboundItem(
            order_id=o.id, sku_id=sku_id, sn=req.sn, location_id=req.location_id,
            status="PICKED", operator_id=operator_id, operated_at=now,
        ))
    o.actual_qty = (o.actual_qty or 0) + req.qty
    o.version += 1
    db.flush()

    # 实发 > 计划禁止提交（PRD 6.5.1）——拣货阶段就拦掉，别等到提交
    if o.actual_qty > o.plan_qty:
        raise BizError(
            Codes.BIZ_RULE,
            f"实发 {o.actual_qty} 超过计划 {o.plan_qty}，禁止超发",
            data={"plan_qty": o.plan_qty, "actual_qty": o.actual_qty},
        )

    if o.status == str(OrderStatus.PENDING):
        o.status = transit("OUTBOUND", o.status, str(OrderStatus.PARTIAL))
    db.commit()

    return {
        "order_id": o.id,
        "status": o.status,
        "picked": o.actual_qty,
        "plan_qty": o.plan_qty,
        "remain": max(0, o.plan_qty - o.actual_qty),
    }


def _sku_from_order(db: Session, o: OutboundOrder) -> int | None:
    return None


# ---------------------------------------------------------------- 提交
def submit(db: Session, order_id: int, req: OutboundSubmitReq, operator_id: int) -> dict:
    """提交出库：扣减已拣未发的库存 + 状态推进（接口 29）。

    只扣 `status == PICKED` 的行，所以提交可重复调用：每次只发新增的拣货，
    支持「拣一批发一批」。回传 MES/ERP 在 B06（T-05-2）。
    """
    o = db.get(OutboundOrder, order_id)
    if o is None:
        raise BizError(Codes.BAD_REQUEST, "出库单不存在")
    if is_terminal("OUTBOUND", o.status):
        raise BizError(Codes.ORDER_CLOSED, f"出库单已终态（{o.status}）")

    # 盘亏单由盘点生成，明细在提交前就定好了（数量来自实盘），
    # 仓管员只需确认实物已出库 —— 所以 PENDING 行也直接发。
    statuses = ("PICKED", "PENDING") if o.type == str(OutboundType.LOSS) else ("PICKED",)
    pending = db.execute(
        select(OutboundItem).where(
            OutboundItem.order_id == o.id, OutboundItem.status.in_(statuses)
        )
    ).scalars().all()
    if not pending:
        raise BizError(Codes.BIZ_RULE, "没有待发货的拣货记录")

    # 实发 > 计划禁止提交
    if o.actual_qty > o.plan_qty:
        raise BizError(Codes.BIZ_RULE,
                       f"实发 {o.actual_qty} 超过计划 {o.plan_qty}，禁止超发")

    # 实发 < 计划必须填原因（BR-016）
    if o.actual_qty != o.plan_qty and not (req.reason or "").strip():
        raise BizError(Codes.BAD_REQUEST,
                       f"实发 {o.actual_qty} 与计划 {o.plan_qty} 不一致，必须填写差异原因")
    if req.reason and len(req.reason.strip()) < 5:
        raise BizError(Codes.BAD_REQUEST, "差异原因至少 5 个字")

    # 一行一件，所以一行扣一件
    sku_type = sku_type_of(o.type)
    moves = [Move(sku_type, i.sku_id, i.location_id, -1) for i in pending]
    apply_many(db, moves, biz_type=str(_BIZ_TYPE[o.type]), biz_no=o.no, operator_id=operator_id)

    for i in pending:
        i.status = "SHIPPED"
        i.operated_at = _NOW()
        i.operator_id = operator_id

    o.status = advance_by_qty("OUTBOUND", o.status, o.actual_qty, o.plan_qty)
    if o.actual_qty >= o.plan_qty:
        o.finished_at = _NOW()
    o.version += 1
    if req.reason:
        o.config_snapshot = {**(o.config_snapshot or {}), "submit_reason": req.reason.strip()}
    db.commit()

    return {
        "order_id": o.id,
        "no": o.no,
        "status": o.status,
        "actual_qty": o.actual_qty,
        "remain": max(0, o.plan_qty - o.actual_qty),
        "finished_at": _s(o.finished_at),
    }


# ---------------------------------------------------------------- 作废
def void(db: Session, order_id: int, req: OutboundVoidReq, operator_id: int) -> dict:
    """作废出库单（接口 38）。已发货的库存用反向流水冲销（BR-002）。"""
    o = db.get(OutboundOrder, order_id)
    if o is None:
        raise BizError(Codes.BAD_REQUEST, "出库单不存在")
    new_status = transit("OUTBOUND", o.status, str(OrderStatus.VOID), reason=req.reason)

    shipped = db.execute(
        select(OutboundItem).where(
            OutboundItem.order_id == o.id, OutboundItem.status == "SHIPPED"
        )
    ).scalars().all()
    if shipped:
        sku_type = sku_type_of(o.type)
        apply_many(
            db,
            [Move(sku_type, i.sku_id, i.location_id, 1) for i in shipped],
            biz_type=str(BizType.VOID_REVERSE),
            biz_no=o.no,
            operator_id=operator_id,
        )

    o.status = new_status
    o.finished_at = _NOW()
    o.version += 1
    o.config_snapshot = {**(o.config_snapshot or {}), "void_reason": req.reason.strip()}
    db.commit()
    return {"order_id": o.id, "no": o.no, "status": o.status}


def status_counts(db: Session) -> dict:
    rows = db.execute(
        select(OutboundOrder.type, OutboundOrder.status, func.count())
        .group_by(OutboundOrder.type, OutboundOrder.status)
    ).all()
    out: dict[str, dict[str, int]] = {}
    for t, s, n in rows:
        out.setdefault(t, {})[s] = int(n)
    return out
