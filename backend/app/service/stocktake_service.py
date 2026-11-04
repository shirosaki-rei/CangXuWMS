"""盘点服务（接口 13–15、30–32，页面 P15/P16）。

流程（PRD 5.4 / 第 9 章状态机）：
  创建 PENDING（锁定库位）→ 扫码实盘 → 盘完转 CONFIRMING → 主管提交 DONE
  提交时按差异生成盘亏出库单 SL / 盘盈入库单 SG，写库存调整流水，再解锁库位。

盲盘（BR-024）：方式在创建时固化；盲盘下账面数对操作员不可见，提交后才揭晓。
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
    OutboundType,
    SkuType,
    StocktakeMode,
    StocktakeStatus,
    StocktakeType,
)
from app.domain.machine import is_terminal, transit
from app.domain.models import (
    InboundItem,
    InboundOrder,
    Inventory,
    Location,
    Material,
    OutboundItem,
    OutboundOrder,
    Stocktake,
    StocktakeItem,
    Warehouse,
)
from app.domain.rules import gen_no, location_status_after
from app.schemas.stocktake import CountReq, StocktakeCreateReq, StocktakeSubmitReq
from app.service.admin_service import get_config

_NOW = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731

TYPE_LABELS = {
    str(StocktakeType.FULL): "全盘",
    str(StocktakeType.SPOT): "抽盘",
    str(StocktakeType.CYCLE): "循环盘点",
}
MODE_LABELS = {str(StocktakeMode.BLIND): "盲盘", str(StocktakeMode.OPEN): "明盘"}
STATUS_LABELS = {
    str(StocktakeStatus.PENDING): "待盘点",
    str(StocktakeStatus.COUNTING): "盘点中",
    str(StocktakeStatus.CONFIRMING): "待确认",
    str(StocktakeStatus.DONE): "已完成",
    str(StocktakeStatus.CANCELED): "已取消",
}


def _s(v) -> str:
    return v.isoformat(sep=" ", timespec="seconds") if v else ""


def _default_mode(db: Session) -> str:
    raw = str(get_config(db, "stocktake_mode", "BLIND")).upper()
    return str(StocktakeMode.OPEN) if raw == "OPEN" else str(StocktakeMode.BLIND)


# ---------------------------------------------------------------- 创建
def create(db: Session, body: StocktakeCreateReq, operator_id: int) -> dict:
    """创建即锁定库位（BR-007）。只锁「空闲/占用」的库位，
    人工锁定或维保的不纳入盘点，也不会在提交时被误解锁。"""
    wh = db.get(Warehouse, body.warehouse_id)
    if wh is None:
        raise BizError(Codes.BAD_REQUEST, "仓库不存在")

    stmt = select(Location).where(
        Location.warehouse_id == body.warehouse_id,
        Location.status.in_((str(LocationStatus.IDLE), str(LocationStatus.OCCUPIED))),
    )
    if body.location_ids:
        stmt = stmt.where(Location.id.in_(body.location_ids))
    locs = db.execute(stmt).scalars().all()
    if not locs:
        raise BizError(Codes.BIZ_RULE, "该范围内没有可盘点的库位")

    loc_ids = [l.id for l in locs]
    inv_rows = db.execute(
        select(Inventory).where(
            Inventory.sku_type == str(SkuType.MATERIAL),
            Inventory.location_id.in_(loc_ids),
            Inventory.qty > 0,
        )
    ).scalars().all()

    mode = body.mode or _default_mode(db)
    st = Stocktake(
        no=gen_no("PD"),
        type=body.type,
        warehouse_id=body.warehouse_id,
        mode=mode,
        status=str(StocktakeStatus.PENDING),
        total=len(inv_rows),
        done=0,
        operator_id=operator_id,
        version=0,
    )
    db.add(st)
    db.flush()

    for inv in inv_rows:
        db.add(StocktakeItem(
            stocktake_id=st.id, material_id=inv.sku_id, location_id=inv.location_id,
            book_qty=inv.qty, real_qty=None,
        ))

    for loc in locs:
        loc.status = str(LocationStatus.LOCKED)
        loc.used_pallet = loc.used_pallet  # 保持不动，仅状态改为锁定

    db.commit()
    return {
        "id": st.id,
        "no": st.no,
        "mode": st.mode,
        "mode_label": MODE_LABELS.get(st.mode, st.mode),
        "total": st.total,
        "locked_locations": len(locs),
    }


# ---------------------------------------------------------------- 查询
def list_stocktakes(db: Session, *, q) -> tuple[list[dict], int]:
    stmt = select(Stocktake)
    if q.no:
        stmt = stmt.where(Stocktake.no.like(f"%{q.no}%"))
    if q.type:
        stmt = stmt.where(Stocktake.type == q.type)
    if q.status:
        stmt = stmt.where(Stocktake.status == q.status)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(
        stmt.order_by(Stocktake.id.desc()).limit(q.page_size).offset((q.page - 1) * q.page_size)
    ).scalars().all()

    wh_names = {
        r[0]: r[1]
        for r in db.execute(select(Warehouse.id, Warehouse.name)).all()
    }
    return [
        {
            "id": s.id,
            "no": s.no,
            "type": s.type,
            "type_label": TYPE_LABELS.get(s.type, s.type),
            "mode": s.mode,
            "mode_label": MODE_LABELS.get(s.mode, s.mode),
            "warehouse_id": s.warehouse_id,
            "warehouse_name": wh_names.get(s.warehouse_id),
            "status": s.status,
            "status_label": STATUS_LABELS.get(s.status, s.status),
            "total": s.total,
            "done": s.done,
            "undone": max(0, s.total - s.done),
            "diff_loss": s.diff_loss,
            "diff_gain": s.diff_gain,
            "operator_id": s.operator_id,
            "created_at": _s(s.created_at),
            "finished_at": _s(s.finished_at),
        }
        for s in rows
    ], int(total or 0)


def get_stocktake(db: Session, sid: int) -> dict:
    s = db.get(Stocktake, sid)
    if s is None:
        raise BizError(Codes.BAD_REQUEST, "盘点单不存在")
    wh = db.get(Warehouse, s.warehouse_id)
    return {
        "id": s.id,
        "no": s.no,
        "type": s.type,
        "type_label": TYPE_LABELS.get(s.type, s.type),
        "mode": s.mode,
        "mode_label": MODE_LABELS.get(s.mode, s.mode),
        "warehouse_id": s.warehouse_id,
        "warehouse_name": wh.name if wh else None,
        "status": s.status,
        "status_label": STATUS_LABELS.get(s.status, s.status),
        "total": s.total,
        "done": s.done,
        "undone": max(0, s.total - s.done),
        "diff_loss": s.diff_loss,
        "diff_gain": s.diff_gain,
        "operator_id": s.operator_id,
        "created_at": _s(s.created_at),
        "finished_at": _s(s.finished_at),
        "terminal": is_terminal("STOCKTAKE", s.status),
    }


def list_items(db: Session, sid: int, *, blind: bool) -> list[dict]:
    """盘点明细（接口 15）。

    blind=True 时抹掉账面与差异——盲盘模式下 PC 与 PDA 都不显示（PRD 6.6.3），
    不是藏在字段名里，而是真的不返回。
    """
    s = db.get(Stocktake, sid)
    if s is None:
        raise BizError(Codes.BAD_REQUEST, "盘点单不存在")
    hide = blind and s.mode == str(StocktakeMode.BLIND)

    rows = db.execute(
        select(StocktakeItem, Material.code, Material.name, Material.unit, Location.code)
        .join(Material, Material.id == StocktakeItem.material_id)
        .join(Location, Location.id == StocktakeItem.location_id)
        .where(StocktakeItem.stocktake_id == sid)
        .order_by(StocktakeItem.location_id, StocktakeItem.material_id)
    ).all()

    out = []
    for it, mcode, mname, unit, lcode in rows:
        diff = None if it.real_qty is None else it.real_qty - it.book_qty
        d = {
            "id": it.id,
            "material_id": it.material_id,
            "material_code": mcode,
            "material_name": mname,
            "unit": unit,
            "location_id": it.location_id,
            "location_code": lcode,
            "real_qty": it.real_qty,
            "counted": it.real_qty is not None,
        }
        if not hide:
            d["book_qty"] = it.book_qty
            d["diff"] = diff
        out.append(d)
    return out


# ---------------------------------------------------------------- 实盘
def count(db: Session, sid: int, body: CountReq, operator_id: int) -> dict:
    """提交一个库位的实盘数（接口 30）。

    允许出现账面没有的 (库位, 物料)，此时按 book_qty=0 建行——这就是盘盈的来源。
    """
    s = db.get(Stocktake, sid)
    if s is None:
        raise BizError(Codes.BAD_REQUEST, "盘点单不存在")
    if is_terminal("STOCKTAKE", s.status):
        raise BizError(Codes.ORDER_CLOSED, f"盘点单已终态（{s.status}）")

    loc = db.get(Location, body.location_id)
    if loc is None:
        raise BizError(Codes.BAD_REQUEST, "库位不存在")
    if loc.warehouse_id != s.warehouse_id:
        raise BizError(Codes.BAD_REQUEST, "该库位不属于本盘点单的仓库")
    if db.get(Material, body.material_id) is None:
        raise BizError(Codes.BAD_REQUEST, "物料不存在")

    item = db.execute(
        select(StocktakeItem).where(
            StocktakeItem.stocktake_id == sid,
            StocktakeItem.location_id == body.location_id,
            StocktakeItem.material_id == body.material_id,
        )
    ).scalar_one_or_none()

    if item is None:
        item = StocktakeItem(
            stocktake_id=sid, material_id=body.material_id, location_id=body.location_id,
            book_qty=0, real_qty=None,
        )
        db.add(item)
        s.total += 1

    item.real_qty = body.real_qty
    db.flush()

    s.done = int(db.execute(
        select(func.count()).select_from(StocktakeItem).where(
            StocktakeItem.stocktake_id == sid, StocktakeItem.real_qty.is_not(None))
    ).scalar())
    s.version += 1

    # 状态推进：首次扫码进入「盘点中」，全部盘完进「待确认」
    if s.status == str(StocktakeStatus.PENDING):
        s.status = transit("STOCKTAKE", s.status, str(StocktakeStatus.COUNTING))
    if s.done >= s.total and s.status == str(StocktakeStatus.COUNTING):
        s.status = transit("STOCKTAKE", s.status, str(StocktakeStatus.CONFIRMING))
    db.commit()

    out = {
        "stocktake_id": s.id,
        "status": s.status,
        "done": s.done,
        "total": s.total,
        "undone": max(0, s.total - s.done),
    }
    # 盲盘不回账面与差异，提交后才揭晓
    if s.mode == str(StocktakeMode.OPEN):
        out["book_qty"] = item.book_qty
        out["diff"] = item.real_qty - item.book_qty
    return out


# ---------------------------------------------------------------- 提交
def submit(db: Session, sid: int, body: StocktakeSubmitReq, operator_id: int) -> dict:
    """提交盘点（接口 31）：生成**待执行**的盈亏单据并解锁库位。

    两步走（PRD 6.5.3「盘亏出库单由主管确认后自动生成，仓管员只执行实物出库」）：
      - 本接口只出单，库存**不动**
      - 仓管员执行对应的盘亏出库单 / 盘盈入库单时才写库存流水

    这样账面差异在实物处理完之前始终可见，符合现场「先盘点、再出库」的顺序。
    """
    s = db.get(Stocktake, sid)
    if s is None:
        raise BizError(Codes.BAD_REQUEST, "盘点单不存在")
    if is_terminal("STOCKTAKE", s.status):
        raise BizError(Codes.ORDER_CLOSED, f"盘点单已终态（{s.status}）")
    if s.done < s.total:
        raise BizError(
            Codes.BIZ_RULE,
            f"还有 {s.total - s.done} 个条目未盘，不允许部分提交",
            data={"undone": s.total - s.done},
        )

    items = db.execute(
        select(StocktakeItem).where(
            StocktakeItem.stocktake_id == sid, StocktakeItem.real_qty.is_not(None))
    ).scalars().all()
    loss = [(i, i.real_qty - i.book_qty) for i in items if i.real_qty < i.book_qty]
    gain = [(i, i.real_qty - i.book_qty) for i in items if i.real_qty > i.book_qty]

    docs = {"loss_no": None, "gain_no": None}

    if loss:
        # 盘亏出库单 SL：待执行，等仓管员确认实物已出库
        qty_total = sum(abs(d) for _, d in loss)
        order = OutboundOrder(
            no=gen_no("SL"), type=str(OutboundType.LOSS), source_no=s.no,
            status=str(OrderStatus.PENDING),
            plan_qty=qty_total,
            actual_qty=qty_total,  # 数量由盘点确定，不需要再扫
            creator_id=operator_id,
        )
        db.add(order)
        db.flush()
        for it, d in loss:
            for _ in range(abs(d)):
                db.add(OutboundItem(order_id=order.id, sku_id=it.material_id,
                                    location_id=it.location_id, status="PENDING"))
        docs["loss_no"] = order.no

    if gain:
        # 盘盈入库单 SG：待执行
        qty_total = sum(d for _, d in gain)
        order_in = InboundOrder(
            no=gen_no("SG"), type=str(InboundType.GAIN), source_no=s.no,
            status=str(OrderStatus.PENDING),
            plan_qty=qty_total,
            actual_qty=qty_total,
            creator_id=operator_id,
        )
        db.add(order_in)
        db.flush()
        for it, d in gain:
            db.add(InboundItem(order_id=order_in.id, sku_id=it.material_id,
                               qty=d, location_id=it.location_id))
        docs["gain_no"] = order_in.no

    s.status = transit("STOCKTAKE", s.status, str(StocktakeStatus.DONE))
    s.diff_loss = len(loss)
    s.diff_gain = len(gain)
    s.finished_at = _NOW()
    s.version += 1

    # 解锁：只解锁本仓、当前为 LOCKED 的库位，按库存推回空闲/占用
    locs = db.execute(
        select(Location).where(
            Location.warehouse_id == s.warehouse_id,
            Location.status == str(LocationStatus.LOCKED),
        )
    ).scalars().all()
    for loc in locs:
        qty = db.execute(
            select(func.coalesce(func.sum(Inventory.qty), 0)).where(
                Inventory.location_id == loc.id)
        ).scalar()
        loc.status = location_status_after(str(LocationStatus.IDLE), int(qty))
    db.commit()

    return {
        "id": s.id,
        "no": s.no,
        "status": s.status,
        "diff_loss": s.diff_loss,
        "diff_gain": s.diff_gain,
        **docs,
        # 单据是「待执行」的：库存要等对应单据被提交后才变
        "docs_pending": bool(docs["loss_no"] or docs["gain_no"]),
    }
