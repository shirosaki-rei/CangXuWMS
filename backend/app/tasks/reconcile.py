"""每日对账（T-05-3）。

单机部署没有上游数据库可拉，所以对账做两层：
  1. **内部一致性**：每个 (SKU, 库位) 的 `inventory.qty` 必须等于 `txn` 的累计增量；
     不等就说明有人在流水之外改了库存——这是最危险的一类错账。
  2. **单据-流水一致性**：终态单据必须有对应流水，反之亦然。

差异写 `reconcile_diff`（uk_biz 保证同一天同一单不重复记）。MES/ERP 的字段级对账
等对方提供回查接口后再接（接口文档 6 I-01）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.domain.models import (
    InboundOrder,
    Inventory,
    OutboundOrder,
    ReconcileDiff,
    Txn,
)

log = get_logger("wms.reconcile")


def _record(db, biz_date: date, direction: str, biz_no: str, diff_type: str,
            local: str | None, remote: str | None) -> None:
    exist = db.execute(
        select(ReconcileDiff).where(
            ReconcileDiff.biz_date == biz_date,
            ReconcileDiff.direction == direction,
            ReconcileDiff.biz_no == biz_no,
            ReconcileDiff.diff_type == diff_type,
        )
    ).scalar_one_or_none()
    if exist is None:
        db.add(ReconcileDiff(biz_date=biz_date, direction=direction, biz_no=biz_no,
                             diff_type=diff_type, local_val=local, remote_val=remote))
    else:
        exist.local_val, exist.remote_val = local, remote


def run(db=None, *, biz_date: date | None = None) -> dict:
    """返回 {checked, diffs}。可被 APScheduler 直接调用。"""
    own = db is None
    db = db or SessionLocal()
    today = biz_date or datetime.now(timezone.utc).date()
    diffs = 0
    try:
        # 1) 库存 vs 流水累计
        rows = db.execute(
            select(Inventory.sku_type, Inventory.sku_id, Inventory.location_id,
                   Inventory.qty,
                   func.coalesce(func.sum(Txn.qty_delta), 0).label("txn_sum"))
            .outerjoin(
                Txn,
                (Txn.sku_type == Inventory.sku_type)
                & (Txn.sku_id == Inventory.sku_id)
                & (Txn.location_id == Inventory.location_id),
            )
            .group_by(Inventory.id, Inventory.sku_type, Inventory.sku_id,
                      Inventory.location_id, Inventory.qty)
        ).all()
        for sku_type, sku_id, loc_id, qty, txn_sum in rows:
            if int(qty) != int(txn_sum):
                _record(db, today, "ERP", f"{sku_type}-{sku_id}-{loc_id}", "QTY",
                        str(qty), str(int(txn_sum)))
                diffs += 1

        # 2) 终态单据必须有流水
        for model, biz_types in ((InboundOrder, ("PURCHASE", "PRODUCT", "RETURN", "GAIN")),
                                 (OutboundOrder, ("SALES", "PICK", "LOSS"))):
            orders = db.execute(
                select(model.no).where(model.status == "DONE",
                                       model.finished_at >= datetime.combine(
                                           today - timedelta(days=1), datetime.min.time()))
            ).scalars().all()
            for no in orders:
                n = db.execute(select(func.count()).select_from(Txn).where(
                    Txn.biz_no == no)).scalar()
                if not n:
                    _record(db, today, "MES", no, "MISSING", "DONE", "无流水")
                    diffs += 1

        db.commit()
    finally:
        if own:
            db.close()

    if diffs:
        log.error("reconcile %s: %d 处差异，已写入 reconcile_diff", today, diffs)
    else:
        log.info("reconcile %s: 无差异", today)
    return {"biz_date": str(today), "checked": len(rows), "diffs": diffs}


if __name__ == "__main__":  # pragma: no cover
    print(run())
