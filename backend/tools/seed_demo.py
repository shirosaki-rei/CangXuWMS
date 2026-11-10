"""演示/测试数据：造几条**已完结**的历史单据与对应库存。

为什么不放进 `app.seed`：
  测试的 `seeded` 夹具也会跑 `seed()`，而很多用例断言「初始库存为 0」
  （如 test_inbound_api::test_提交入库落库存并写流水 开头 `assert _stock(sku) == 0`）。
  共享种子里灌库存会让这些前提失效，所以演示数据单独一个脚本、只在需要时手动跑。

用法（在 backend 目录）：
    PYTHONPATH=. ./.venv/Scripts/python.exe tools/seed_demo.py
    PYTHONPATH=. ./.venv/Scripts/python.exe tools/seed_demo.py --reset   # 先删掉本脚本造的数据

幂等：同单号已存在就跳过；--reset 只删本脚本创建的单号，不动 app.seed 的数据。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.domain.models import (
    InboundItem,
    InboundOrder,
    Inventory,
    Location,
    Material,
    Product,
    Txn,
)
from app.domain.stock import Move, apply_many

NOW = datetime.now(timezone.utc).replace(tzinfo=None)

# 本脚本创建的单号前缀，--reset 只清理这些
DEMO_INBOUND = [
    # (单号, 类型, 来源单号, 物料/产品编码, 数量, 天数前)
    ("PR20260120001", "PURCHASE", "JY20260120001", "DSP-AMOLED-67-FULL", 120, 7),
    ("PI20260118001", "PRODUCT", "RWD20260118001", "A3288", 60, 9),
    ("SG20260115001", "GAIN", None, "PCB-MAIN-V3", 8, 12),
]


def _mat_id(db, code: str, sku_type: str) -> int:
    table = Product if sku_type == "PRODUCT" else Material
    return db.execute(select(table.id).where(table.code == code)).scalar_one()


def _pick_locations(db, n: int) -> list[Location]:
    """取 n 个普通、空闲的库位（避开危品/恒温，免得 BR-013 在演示时挡路）。"""
    return list(db.execute(
        select(Location).where(Location.type == "NORMAL", Location.status.in_(("IDLE", "OCCUPIED")))
        .order_by(Location.id).limit(n)
    ).scalars())


def reset(db) -> None:
    nos = [n for n, *_ in DEMO_INBOUND]
    db.execute(delete(Txn).where(Txn.biz_no.in_(nos)))
    ids = db.execute(select(InboundOrder.id).where(InboundOrder.no.in_(nos))).scalars().all()
    if ids:
        db.execute(delete(InboundItem).where(InboundItem.order_id.in_(ids)))
        db.execute(delete(InboundOrder).where(InboundOrder.id.in_(ids)))
    db.commit()
    print(f"已清理演示数据：{len(nos)} 张单据及其流水（库存行保留，按需 reset_db 重建）")


def seed(db) -> None:
    locs = _pick_locations(db, 3)
    if len(locs) < 1:
        print("没有可用库位，先跑 app.seed")
        return

    created = 0
    for i, (no, otype, source, code, qty, days) in enumerate(DEMO_INBOUND):
        if db.execute(select(InboundOrder.id).where(InboundOrder.no == no)).first():
            print(f"跳过 {no}（已存在）")
            continue
        sku_type = "PRODUCT" if otype == "PRODUCT" else "MATERIAL"
        sku_id = _mat_id(db, code, sku_type)
        loc = locs[i % len(locs)]
        when = NOW - timedelta(days=days)

        order = InboundOrder(
            no=no, type=otype, source_no=source, status="DONE",
            plan_qty=qty, actual_qty=qty, creator_id=1, checker_id=1,
            created_at=when, finished_at=when,
        )
        db.add(order)
        db.flush()
        db.add(InboundItem(order_id=order.id, sku_id=sku_id, qty=qty,
                           location_id=loc.id, box_code=f"BOX{no[-8:]}"))

        biz = {"PURCHASE": "PURCHASE_IN", "PRODUCT": "PRODUCT_IN", "GAIN": "GAIN_IN"}[otype]
        apply_many(db, [Move(sku_type, sku_id, loc.id, qty)],
                   biz_type=biz, biz_no=no, operator_id=1)

        # 流水与单据的时间对齐到历史，否则列表里全是「今天」
        db.flush()
        db.execute(
            Txn.__table__.update().where(Txn.biz_no == no).values(created_at=when)
        )
        db.commit()
        created += 1
        print(f"创建 {no}：{code} × {qty} → {loc.code}（{when:%Y-%m-%d}）")

    print(f"\n完成，新增 {created} 张已完结单据。")
    print("库存列表现状：")
    for sku_type, table in (("PRODUCT", Product), ("MATERIAL", Material)):
        rows = db.execute(
            select(table.code, table.name, Inventory.qty)
            .join(Inventory, (Inventory.sku_id == table.id) & (Inventory.sku_type == sku_type))
            .order_by(table.code)
        ).all()
        for code, name, q in rows:
            print(f"  [{sku_type}] {code} {name} = {q}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="先删除本脚本创建的单据与流水")
    args = ap.parse_args()
    with SessionLocal() as db:
        if args.reset:
            reset(db)
        seed(db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
