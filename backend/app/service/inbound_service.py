"""入库单服务：列表 / 详情 / 扫码收货 / 提交 / 作废（接口 7/8/26/27/37，页面 P05–P09）。

涉及规则：
  BR-004 采购入库必须关联检验单
  BR-010 同一 SN 不可同时存在于两张未关闭的单据
  BR-013 危品库位只能存放危品物料
  BR-011 终态不可回退，作废需原因并留痕
  BR-001/002 库存只能被单据改变、流水只增不改
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BizError, Codes
from app.domain.enums import (
    BizType,
    InboundType,
    LocationStatus,
    OrderStatus,
    SkuType,
)
from app.domain.machine import advance_by_qty, is_terminal, transit
from app.domain.models import (
    InboundItem,
    InboundOrder,
    Inspection,
    InspectionItem,
    Location,
    Material,
    Product,
)
from app.domain.rules import location_mismatch_reason
from app.domain.stock import Move, apply_many
from app.schemas.inbound import ScanReq, SubmitReq, VoidReq

_NOW = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731

# 入库单类型 → SKU 类型。采购/退料/盘盈入的都是物料，产品入库入的是成品。
_SKU_TYPE = {
    str(InboundType.PRODUCT): str(SkuType.PRODUCT),
    str(InboundType.PURCHASE): str(SkuType.MATERIAL),
    str(InboundType.RETURN): str(SkuType.MATERIAL),
    str(InboundType.GAIN): str(SkuType.MATERIAL),
}

# 入库单类型 → 落库流水业务类型
_BIZ_TYPE = {
    str(InboundType.PRODUCT): BizType.PRODUCT_IN,
    str(InboundType.PURCHASE): BizType.PURCHASE_IN,
    str(InboundType.RETURN): BizType.RETURN_IN,
    str(InboundType.GAIN): BizType.GAIN_IN,
}

TYPE_LABELS = {
    str(InboundType.PRODUCT): "产品入库",
    str(InboundType.PURCHASE): "采购入库",
    str(InboundType.RETURN): "生产退料",
    str(InboundType.GAIN): "盘盈入库",
}

STATUS_LABELS = {
    str(OrderStatus.PENDING): "待入库",
    str(OrderStatus.PARTIAL): "部分入库",
    str(OrderStatus.DONE): "已入库",
    str(OrderStatus.VOID): "已作废",
}


def sku_type_of(order_type: str) -> str:
    return _SKU_TYPE.get(order_type, str(SkuType.MATERIAL))


def _s(v) -> str:
    return v.isoformat(sep=" ", timespec="seconds") if v else ""


def _item_dict(it: InboundItem) -> dict:
    return {
        "id": it.id,
        "sku_id": it.sku_id,
        "box_code": it.box_code,
        "sn": it.sn,
        "qty": it.qty,
        "location_id": it.location_id,
    }


def _order_dict(db: Session, o: InboundOrder, with_items: bool = False) -> dict:
    d = {
        "id": o.id,
        "no": o.no,
        "type": o.type,
        "type_label": TYPE_LABELS.get(o.type, o.type),
        "source_no": o.source_no,
        "supplier_id": o.supplier_id,
        "status": o.status,
        "status_label": STATUS_LABELS.get(o.status, o.status),
        "plan_qty": o.plan_qty,
        "actual_qty": o.actual_qty,
        "creator_id": o.creator_id,
        "checker_id": o.checker_id,
        "created_at": _s(o.created_at),
        "finished_at": _s(o.finished_at),
        "version": o.version,
        "terminal": is_terminal("INBOUND", o.status),
    }
    if with_items:
        items = db.execute(
            select(InboundItem).where(InboundItem.order_id == o.id).order_by(InboundItem.id)
        ).scalars().all()
        d["items"] = [_item_dict(i) for i in items]
        # 明细行数与计划数不一致时前端要高亮（PRD 6.4.5）
        d["qty_mismatch"] = sum(i.qty for i in items) != o.plan_qty
    return d


# ---------------------------------------------------------------- 查询
def list_orders(db: Session, *, scope: list[int] | None, q) -> tuple[list[dict], int]:
    stmt = select(InboundOrder)
    if q.type:
        stmt = stmt.where(InboundOrder.type == q.type)
    if q.status:
        stmt = stmt.where(InboundOrder.status == q.status)
    if q.no:
        stmt = stmt.where(InboundOrder.no.like(f"%{q.no}%"))
    if q.source_no:
        stmt = stmt.where(InboundOrder.source_no.like(f"%{q.source_no}%"))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(
        stmt.order_by(InboundOrder.id.desc())
        .limit(q.page_size)
        .offset((q.page - 1) * q.page_size)
    ).scalars().all()

    out = []
    for o in rows:
        d = _order_dict(db, o)
        # 列表要显示箱码与库位，取首条明细
        first = db.execute(
            select(InboundItem).where(InboundItem.order_id == o.id).order_by(InboundItem.id)
        ).scalars().first()
        d["box_code"] = first.box_code if first else None
        d["location_id"] = first.location_id if first else None
        out.append(d)
    return out, int(total or 0)


def get_order(db: Session, order_id: int) -> dict:
    o = db.get(InboundOrder, order_id)
    if o is None:
        raise BizError(Codes.BAD_REQUEST, "入库单不存在")
    d = _order_dict(db, o, with_items=True)
    # 明细里的库位编码与 SKU 编码，前端要用
    items = db.execute(
        select(InboundItem).where(InboundItem.order_id == o.id).order_by(InboundItem.id)
    ).scalars().all()
    loc_ids = {i.location_id for i in items if i.location_id}
    sku_ids = {i.sku_id for i in items}
    locs = {
        r[0]: r[1]
        for r in db.execute(select(Location.id, Location.code).where(Location.id.in_(loc_ids)))
    } if loc_ids else {}
    # 必须按单据的 sku_type 选表：成品与物料共用一套自增 id，
    # 先查 product 会在「同 id 的物料单」上拿到错的编码
    sku_table = Product if sku_type_of(o.type) == str(SkuType.PRODUCT) else Material
    skus = {
        r[0]: r[1]
        for r in db.execute(select(sku_table.id, sku_table.code).where(sku_table.id.in_(sku_ids)))
    } if sku_ids else {}
    for it in d["items"]:
        it["location_code"] = locs.get(it["location_id"])
        it["sku_code"] = skus.get(it["sku_id"])
    return d


# ---------------------------------------------------------------- 扫码收货
def _check_location(db: Session, location_id: int, sku_id: int | None,
                    order_type: str) -> Location:
    """BR-013：危品库位只能放危品、恒温库位只能放控温物料；锁定/维保中不能上架。

    只在**物料**入库单上做属性匹配——成品单的 sku_id 是 product.id，
    拿它去查 material 表会撞上同 id 的物料（两个表共用一套自增 id），
    于是成品单会被错误地按物料规则拦下来。
    """
    loc = db.get(Location, location_id)
    if loc is None:
        raise BizError(Codes.BAD_REQUEST, "库位不存在")
    if loc.status in (LocationStatus.LOCKED, LocationStatus.MAINTAIN):
        label = "锁定" if loc.status == str(LocationStatus.LOCKED) else "维保"
        raise BizError(Codes.BIZ_RULE, f"库位 {loc.code} 处于「{label}」状态，不能上架")
    if sku_id is not None and sku_type_of(order_type) == str(SkuType.MATERIAL):
        material = db.get(Material, sku_id)
        if material is not None:
            reason = location_mismatch_reason(loc.type, material.is_dangerous,
                                              material.temp_control)
            if reason:
                raise BizError(Codes.BIZ_RULE, reason)
    return loc


def scan(db: Session, order_id: int, req: ScanReq, operator_id: int) -> dict:
    """扫码收货：查重 → 校验库位 → 追加明细 → 推进状态（接口 26）。"""
    o = db.get(InboundOrder, order_id)
    if o is None:
        raise BizError(Codes.BAD_REQUEST, "入库单不存在")
    if is_terminal("INBOUND", o.status):
        raise BizError(Codes.ORDER_CLOSED, f"入库单已终态（{o.status}），不能继续扫码")

    if not req.box_code and not req.sn:
        raise BizError(Codes.BAD_REQUEST, "箱码与 SN 至少要填一个")

    # 箱码查重：同一张单内重复即拒（PRD 6.4.1「该箱码已入库」）
    if req.box_code:
        dup = db.execute(
            select(InboundItem.id).where(
                InboundItem.order_id == order_id, InboundItem.box_code == req.box_code
            )
        ).first()
        if dup:
            raise BizError(Codes.DUPLICATE, f"箱码 {req.box_code} 已扫过，请勿重复提交",
                           data={"box_code": req.box_code, "duplicate": True})

    # BR-010：同一 SN 不能同时挂在两张未关闭的单上
    if req.sn:
        clash = db.execute(
            select(InboundItem.id, InboundItem.order_id)
            .join(InboundOrder, InboundOrder.id == InboundItem.order_id)
            .where(
                InboundItem.sn == req.sn,
                InboundItem.order_id != order_id,
                InboundOrder.status.in_((str(OrderStatus.PENDING), str(OrderStatus.PARTIAL))),
            )
        ).first()
        if clash:
            raise BizError(
                Codes.DUPLICATE,
                f"SN {req.sn} 已存在于未关闭的入库单 #{clash[1]}（BR-010）",
                data={"sn": req.sn, "duplicate": True},
            )

    # 本单 SKU：取明细第一行（四类入库单都是单 SKU），没有则从来源单据推断
    first = db.execute(
        select(InboundItem).where(InboundItem.order_id == o.id).order_by(InboundItem.id)
    ).scalars().first()
    sku_id = first.sku_id if first else _sku_from_order(db, o)
    if sku_id is None:
        raise BizError(Codes.BIZ_RULE, "入库单没有可入账的 SKU，请先关联来源单据")

    # 库位校验（BR-013 + 库位状态）
    if req.location_id is None:
        raise BizError(Codes.BAD_REQUEST, "上架必须扫库位码")
    _check_location(db, req.location_id, sku_id, o.type)

    db.add(InboundItem(order_id=o.id, sku_id=sku_id, box_code=req.box_code, sn=req.sn,
                       qty=req.qty, location_id=req.location_id))
    o.actual_qty = (o.actual_qty or 0) + req.qty
    o.version += 1
    db.flush()

    # 扫码只把「待入库」推进到「部分入库」；到「已入库」只能走 submit。
    # PRD 第 9 章状态图画的是「扫码数 = 计划数 → 已入库」，但接口 27 又定义了独立的
    # 「提交入库」动作（落库 + 校验）。两者同时生效会导致扫满即终态、永远无法提交，
    # 所以这里只推进到 PARTIAL，DONE 由 submit 独占。
    if o.status == str(OrderStatus.PENDING):
        o.status = transit("INBOUND", o.status, str(OrderStatus.PARTIAL))
    db.commit()

    return {
        "order_id": o.id,
        "status": o.status,
        "scanned": o.actual_qty,
        "plan_qty": o.plan_qty,
        "duplicate": False,
    }


def _sku_from_order(db: Session, o: InboundOrder) -> int | None:
    """从来源单据推断 SKU：检验单 → 物料；MES 推送的产品入库单没有来源，返回 None。"""
    if o.type == str(InboundType.PURCHASE) and o.source_no:
        insp = db.execute(
            select(Inspection).where(Inspection.no == o.source_no)
        ).scalar_one_or_none()
        if insp:
            row = db.execute(
                select(InspectionItem.material_id)
                .where(InspectionItem.inspection_id == insp.id)
                .limit(1)
            ).first()
            return row[0] if row else None
    return None


# ---------------------------------------------------------------- 提交
def submit(db: Session, order_id: int, req: SubmitReq, operator_id: int) -> dict:
    """提交入库：行锁落库 + 状态机 + 写流水（接口 27）。

    X04 提交前校验在 B05；这里只做落库前的最小校验。
    """
    o = db.get(InboundOrder, order_id)
    if o is None:
        raise BizError(Codes.BAD_REQUEST, "入库单不存在")
    if is_terminal("INBOUND", o.status):
        raise BizError(Codes.ORDER_CLOSED, f"入库单已终态（{o.status}）")

    # qty=0 的是来源单据带出来的占位行，没扫过码，不参与落库
    items = [i for i in db.execute(
        select(InboundItem).where(InboundItem.order_id == o.id)
    ).scalars().all() if (i.qty or 0) > 0]
    if not items:
        raise BizError(Codes.BIZ_RULE, "还没有扫码记录，不能提交")

    # 所有明细都必须已指定库位
    no_loc = [i for i in items if not i.location_id]
    if no_loc:
        raise BizError(Codes.BIZ_RULE, f"有 {len(no_loc)} 条明细未指定上架库位")

    # 扫码数与计划数不一致必须填原因（BR-016）
    if o.actual_qty != o.plan_qty and not (req.reason or "").strip():
        raise BizError(Codes.BAD_REQUEST,
                       f"实收 {o.actual_qty} 与计划 {o.plan_qty} 不一致，必须填写差异原因")
    if req.reason and len(req.reason.strip()) < 5:
        raise BizError(Codes.BAD_REQUEST, "差异原因至少 5 个字")

    # BR-004：采购入库必须关联检验单且已检合格
    if o.type == str(InboundType.PURCHASE):
        _assert_purchase_qualified(db, o)

    # 按 (sku, location) 聚合后一次落库，锁序由 stock.apply_many 统一
    sku_type = sku_type_of(o.type)
    moves = [Move(sku_type, i.sku_id, i.location_id, i.qty) for i in items]
    apply_many(db, moves, biz_type=str(_BIZ_TYPE[o.type]), biz_no=o.no, operator_id=operator_id)

    o.status = advance_by_qty("INBOUND", o.status, o.actual_qty, o.plan_qty)
    o.checker_id = operator_id
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
        "finished_at": _s(o.finished_at),
    }


def _assert_purchase_qualified(db: Session, o: InboundOrder) -> None:
    """BR-004：检验单须已检且结果为合格/部分合格/合格（超收）。"""
    if not o.source_no:
        raise BizError(Codes.BIZ_RULE, "采购入库单必须关联检验单号（BR-004）")
    insp = db.execute(
        select(Inspection).where(Inspection.no == o.source_no)
    ).scalar_one_or_none()
    if insp is None:
        raise BizError(Codes.BIZ_RULE, f"检验单 {o.source_no} 不存在")
    if insp.status != "DONE":
        raise BizError(Codes.BIZ_RULE, f"检验单 {o.source_no} 尚未判定完成，不能入库")
    if insp.result not in ("PASS", "PARTIAL", "OVER_PASS"):
        raise BizError(Codes.BIZ_RULE, f"检验单 {o.source_no} 判定为「{insp.result}」，不能入库")


# ---------------------------------------------------------------- 作废
def void(db: Session, order_id: int, req: VoidReq, operator_id: int) -> dict:
    """作废入库单（接口 37）。已落库的库存用反向流水冲销（BR-002）。"""
    o = db.get(InboundOrder, order_id)
    if o is None:
        raise BizError(Codes.BAD_REQUEST, "入库单不存在")
    new_status = transit("INBOUND", o.status, str(OrderStatus.VOID), reason=req.reason)

    # 已落过库的要把库存冲回去。注意按「有没有落库存」判断，不是按状态：
    # 部分入库的单同样可能已经落过库（短收提交），作废时必须冲销。
    if (o.actual_qty or 0) > 0:
        items = db.execute(
            select(InboundItem).where(InboundItem.order_id == o.id, InboundItem.qty > 0)
        ).scalars().all()
        if items:
            sku_type = sku_type_of(o.type)
            apply_many(
                db,
                [Move(sku_type, i.sku_id, i.location_id, -i.qty) for i in items],
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


# ---------------------------------------------------------------- 统计
def status_counts(db: Session, *, scope: list[int] | None = None) -> dict:
    """入库管理页的四类 Tab 角标。"""
    rows = db.execute(
        select(InboundOrder.type, InboundOrder.status, func.count())
        .group_by(InboundOrder.type, InboundOrder.status)
    ).all()
    out: dict[str, dict[str, int]] = {}
    for t, s, n in rows:
        out.setdefault(t, {})[s] = int(n)
    return out
