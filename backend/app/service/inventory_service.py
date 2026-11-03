"""库存与流水查询（接口 4/5/6，页面 P01–P04）。

口径（PRD 6.2 / 10.2）：
  总库存   = inventory.qty（含锁定）
  可用库存 = qty - locked_qty - frozen_qty
  在途库存 = in_transit.qty（ERP 采购订单推送，只读，不参与可用计算）
  盘点差异 = 实盘 - 账面（B04）
"""
from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BizError, Codes
from app.domain.enums import BizType, SkuType
from app.domain.models import InTransit, Inventory, Location, Material, Product, Txn

# 入库类业务类型，用于算「最新入库日期」
_IN_BIZ = (BizType.PURCHASE_IN, BizType.PRODUCT_IN, BizType.RETURN_IN, BizType.GAIN_IN)

BIZ_TYPE_LABELS = {
    BizType.PURCHASE_IN: "采购入库",
    BizType.PRODUCT_IN: "产品入库",
    BizType.RETURN_IN: "生产退料",
    BizType.GAIN_IN: "盘盈入库",
    BizType.SALES_OUT: "销售出库",
    BizType.PICK_OUT: "生产领料",
    BizType.LOSS_OUT: "盘亏出库",
    BizType.MOVE: "移位",
    BizType.STOCKTAKE_IN: "盘盈入库",
    BizType.STOCKTAKE_OUT: "盘亏出库",
    BizType.VOID_REVERSE: "作废冲销",
}


def _parse_dt(v: str | None, *, end: bool = False) -> datetime | None:
    """接受 YYYY-MM-DD 或 ISO 8601；日期型按当天起止补全。"""
    if not v:
        return None
    s = v.strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        try:
            d = datetime.combine(datetime.strptime(s, "%Y-%m-%d").date(),
                                 time.max if end else time.min)
        except ValueError:
            raise BizError(Codes.BAD_REQUEST, f"时间格式无法解析：{v}") from None
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d


def _iso(v) -> str | None:
    return v.isoformat(timespec="seconds") + "Z" if v else None


# ---------------------------------------------------------------- 库存汇总
def _stock_agg(db: Session, sku_type: str):
    """按 SKU 聚合库存。warehouse scope 由调用方过滤。"""
    return (
        select(
            Inventory.sku_id.label("sku_id"),
            func.coalesce(func.sum(Inventory.qty), 0).label("qty"),
            func.coalesce(func.sum(Inventory.locked_qty), 0).label("locked"),
            func.coalesce(func.sum(Inventory.frozen_qty), 0).label("frozen"),
        )
        .where(Inventory.sku_type == sku_type)
        .group_by(Inventory.sku_id)
        .subquery()
    )


def list_products(db: Session, *, scope: list[int] | None, q) -> tuple[list[dict], int]:
    """成品库存（P01）。scope 为 None 表示不限仓库。

    ponytail: 先聚合再在 Python 里切片分页——SKU 万级下聚合才是开销大头，
    LIMIT 省不下多少。真到了十万级再改成窗口函数或子查询分页。
    """
    agg = _stock_agg(db, str(SkuType.PRODUCT))
    last_in = (
        select(Txn.sku_id, func.max(Txn.created_at).label("last_at"))
        .where(Txn.sku_type == str(SkuType.PRODUCT), Txn.biz_type.in_(_IN_BIZ))
        .group_by(Txn.sku_id)
        .subquery()
    )

    stmt = (
        select(Product, agg.c.qty, agg.c.locked, agg.c.frozen, last_in.c.last_at)
        .outerjoin(agg, agg.c.sku_id == Product.id)
        .outerjoin(last_in, last_in.c.sku_id == Product.id)
    )
    if scope is not None:
        if not scope:
            return [], 0
        # 只看得到这些仓库里的库存
        visible = (
            select(Inventory.sku_id)
            .join(Location, Location.id == Inventory.location_id)
            .where(Inventory.sku_type == str(SkuType.PRODUCT), Location.warehouse_id.in_(scope))
            .distinct()
        )
        stmt = stmt.where(Product.id.in_(visible))
    if q.code:
        stmt = stmt.where(Product.code.like(f"%{q.code}%"))
    if q.name:
        stmt = stmt.where(Product.name.like(f"%{q.name}%"))
    if q.date_from or q.date_to:
        lo, hi = _parse_dt(q.date_from), _parse_dt(q.date_to, end=True)
        if lo:
            stmt = stmt.where(last_in.c.last_at >= lo)
        if hi:
            stmt = stmt.where(last_in.c.last_at <= hi)

    # 不用 .nullslast()：MySQL 不支持该语法，而 DESC 本身就把 NULL 排最后，行为一致
    rows = db.execute(stmt.order_by(last_in.c.last_at.desc(), Product.id.desc())).all()
    items = [
        {
            "id": p.id,
            "code": p.code,
            "name": p.name,
            # 规格是多行文本，前端要多行展示
            "spec": [s.strip() for s in (p.spec or "").split("\n") if s.strip()],
            "qty": int(qty or 0),
            "locked": int(locked or 0),
            "frozen": int(frozen or 0),
            "available": int(qty or 0) - int(locked or 0) - int(frozen or 0),
            "unit": p.unit,
            "last_inbound_at": _iso(last_at),
            "zero": int(qty or 0) == 0,
        }
        for p, qty, locked, frozen, last_at in rows
    ]
    start = (q.page - 1) * q.page_size
    return items[start:start + q.page_size], len(items)


def list_materials(db: Session, *, scope: list[int] | None, q) -> tuple[list[dict], int]:
    """物料库存（P02）：总库存 / 可用 / 在途 / 安全库存，低库存标黄。"""
    agg = _stock_agg(db, str(SkuType.MATERIAL))
    transit = (
        select(InTransit.sku_id, func.coalesce(func.sum(InTransit.qty), 0).label("qty"))
        .where(InTransit.sku_type == str(SkuType.MATERIAL))
        .group_by(InTransit.sku_id)
        .subquery()
    )

    stmt = (
        select(Material, agg.c.qty, agg.c.locked, agg.c.frozen, transit.c.qty)
        .outerjoin(agg, agg.c.sku_id == Material.id)
        .outerjoin(transit, transit.c.sku_id == Material.id)
    )
    if scope is not None:
        if not scope:
            return [], 0
        visible = (
            select(Inventory.sku_id)
            .join(Location, Location.id == Inventory.location_id)
            .where(Inventory.sku_type == str(SkuType.MATERIAL), Location.warehouse_id.in_(scope))
            .distinct()
        )
        stmt = stmt.where(Material.id.in_(visible))
    if q.code:
        stmt = stmt.where(Material.code.like(f"%{q.code}%"))
    if q.name:
        stmt = stmt.where(Material.name.like(f"%{q.name}%"))

    rows = db.execute(stmt.order_by(Material.id.desc())).all()
    items = []
    for m, qty, locked, frozen, tqty in rows:
        qty, locked, frozen = int(qty or 0), int(locked or 0), int(frozen or 0)
        available = qty - locked - frozen
        items.append(
            {
                "id": m.id,
                "code": m.code,
                "name": m.name,
                "type": m.type,
                "unit": m.unit,
                "qty": qty,
                "locked": locked,
                "frozen": frozen,
                "available": available,
                "in_transit": int(tqty or 0),
                "safety_stock": m.safety_stock,
                "low_stock": available < m.safety_stock,
            }
        )
    start = (q.page - 1) * q.page_size
    return items[start:start + q.page_size], len(items)


# ---------------------------------------------------------------- 流水
def list_txn(db: Session, *, scope: list[int] | None, q) -> tuple[list[dict], int]:
    """出入库流水（P03/P04）。倒序 + id 次级键保证稳定排序（接口 1.1）。"""
    sku_table = Product if q.sku_type == str(SkuType.PRODUCT) else Material
    stmt = (
        select(Txn, sku_table.code, sku_table.name)
        .join(sku_table, sku_table.id == Txn.sku_id)
        .where(Txn.sku_type == q.sku_type)
    )
    if scope is not None:
        if not scope:
            return [], 0
        stmt = stmt.where(
            Txn.location_id.in_(
                select(Location.id).where(Location.warehouse_id.in_(scope))
            )
        )
    if q.code:
        stmt = stmt.where(sku_table.code.like(f"%{q.code}%"))
    if q.name:
        stmt = stmt.where(sku_table.name.like(f"%{q.name}%"))
    if q.biz_type:
        stmt = stmt.where(Txn.biz_type == q.biz_type)
    lo, hi = _parse_dt(q.date_from), _parse_dt(q.date_to, end=True)
    if lo:
        stmt = stmt.where(Txn.created_at >= lo)
    if hi:
        stmt = stmt.where(Txn.created_at <= hi)

    total = db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar()
    rows = db.execute(
        stmt.order_by(Txn.created_at.desc(), Txn.id.desc())
        .limit(q.page_size)
        .offset((q.page - 1) * q.page_size)
    ).all()
    items = [
        {
            "id": t.id,
            "sku_id": t.sku_id,
            "sku_code": code,
            "sku_name": name,
            "sku_type": t.sku_type,
            "location_id": t.location_id,
            "biz_type": t.biz_type,
            "biz_type_label": BIZ_TYPE_LABELS.get(t.biz_type, t.biz_type),
            "biz_no": t.biz_no,
            "qty_delta": t.qty_delta,
            "balance": t.balance,
            "created_at": _iso(t.created_at),
        }
        for t, code, name in rows
    ]
    return items, int(total or 0)


def export_rows(db: Session, *, scope: list[int] | None, q) -> tuple[list[dict], list[str]]:
    """导出用：一次取全量（上限 5 万行，PRD 6.3.1），不分页。"""
    if q.biz == "txn":
        from app.schemas.inventory import TxnQuery

        items, _ = list_txn(db, scope=scope, q=TxnQuery(**q.model_dump(exclude={"biz"})))
        cols = ["sku_code", "sku_name", "biz_type_label", "biz_no", "qty_delta",
                "balance", "created_at"]
    else:
        from app.schemas.inventory import InventoryQuery

        if q.biz == "inventory_products":
            items, _ = list_products(
                db, scope=scope, q=InventoryQuery(**q.model_dump(exclude={"biz", "sku_type"}))
            )
            cols = ["code", "name", "qty", "locked", "frozen", "available", "unit",
                    "last_inbound_at"]
        else:
            items, _ = list_materials(
                db, scope=scope, q=InventoryQuery(**q.model_dump(exclude={"biz", "sku_type"}))
            )
            cols = ["code", "name", "type", "qty", "available", "in_transit",
                    "safety_stock", "unit"]
    return items, cols


def sku_summary(db: Session, sku_type: str, sku_id: int) -> dict:
    """单个 SKU 的库存汇总，行下钻用。"""
    agg = _stock_agg(db, sku_type)
    row = db.execute(select(agg).where(agg.c.sku_id == sku_id)).first()
    qty, locked, frozen = (int(row[1] or 0), int(row[2] or 0), int(row[3] or 0)) if row else (0, 0, 0)
    table = Product if sku_type == str(SkuType.PRODUCT) else Material
    sku = db.get(table, sku_id)
    if sku is None:
        raise BizError(Codes.BAD_REQUEST, "SKU 不存在")
    return {
        "sku_id": sku_id,
        "sku_type": sku_type,
        "code": sku.code,
        "name": sku.name,
        "qty": qty,
        "locked": locked,
        "frozen": frozen,
        "available": qty - locked - frozen,
    }


def location_breakdown(db: Session, sku_type: str, sku_id: int) -> list[dict]:
    """按库位拆开，用于详情页「库位分布」。"""
    rows = db.execute(
        select(Inventory, Location.code)
        .join(Location, Location.id == Inventory.location_id)
        .where(Inventory.sku_type == sku_type, Inventory.sku_id == sku_id)
        .order_by(Inventory.qty.desc())
    ).all()
    return [
        {
            "location_id": inv.location_id,
            "location_code": loc_code,
            "qty": inv.qty,
            "locked": inv.locked_qty,
            "frozen": inv.frozen_qty,
            "available": inv.available,
        }
        for inv, loc_code in rows
    ]
