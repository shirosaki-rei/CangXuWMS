"""演示数据：3 张历史「已完结」入库单 + 对应库存（演示脚本 0.4 节的初始态）。

为什么要单独一个文件：
`app.seed` 只造主数据与「待执行」单据，**不写 inventory**——README 约定库存只能走
`domain/stock.py`。但演示需要「库里已经有货」的初始状态（库存页三行有货、出库能拣、
流水有历史日期），所以这里按真实入库路径的形态造 3 张已完结单，并通过
`stock.apply_many` 落账，保证 inventory 与 txn 一致、能被 reconcile 校验通过。

目标库存（与演示脚本一致）：
    DSP-AMOLED-67-FULL  120  （采购入库 PR20260120001）
    A3288                60  （产品入库 PI20260118001）
    PCB-MAIN-V3           8  （盘盈入库 SG20260115001，低于安全库存 150 → 演示标黄）

幂等：单号已存在则跳过。
用法：`python -m app.seed_demo`（容器内：`docker compose run --rm --no-deps api python -m app.seed_demo`）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.db import SessionLocal, engine
from app.domain.enums import BizType, InboundType, OrderStatus, SkuType
from app.domain.models import (
    InboundItem,
    InboundOrder,
    Location,
    Material,
    Product,
    Supplier,
    Txn,
)
from app.domain.stock import Move, apply_many

# (单号, 类型, 供应商 code, SKU code, 数量, 目标库位 code, 几天前)
# 库位 code 形如 A1-01-01（区域-序号-仓库id），见 app/seed.py::_locations_for
DEMO_ORDERS = [
    ("PR20260120001", str(InboundType.PURCHASE), "GYS-BYD-002",
     "DSP-AMOLED-67-FULL", 120, "A1-01-01", 12),
    ("PI20260118001", str(InboundType.PRODUCT), None,
     "A3288", 60, "A1-01-02", 10),
    ("SG20260115001", str(InboundType.GAIN), None,
     "PCB-MAIN-V3", 8, "A1-02-01", 7),
]

# 与 inbound_service 的映射保持一致：采购/盘盈入物料，产品入库入成品
_SKU_TYPE = {
    str(InboundType.PURCHASE): str(SkuType.MATERIAL),
    str(InboundType.PRODUCT): str(SkuType.PRODUCT),
    str(InboundType.GAIN): str(SkuType.MATERIAL),
}
_BIZ_TYPE = {
    str(InboundType.PURCHASE): str(BizType.PURCHASE_IN),
    str(InboundType.PRODUCT): str(BizType.PRODUCT_IN),
    str(InboundType.GAIN): str(BizType.GAIN_IN),
}


def _utcnow() -> datetime:
    """与 inbound_service._NOW() 同口径：库里存 UTC 无时区。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sku_id(session, sku_type: str, code: str) -> int:
    model = Material if sku_type == str(SkuType.MATERIAL) else Product
    return session.execute(select(model.id).where(model.code == code)).scalar_one()


def seed_demo(session) -> dict:
    stats = {"order": 0, "txn": 0, "skipped": 0}

    for no, otype, sup_code, sku_code, qty, loc_code, days_ago in DEMO_ORDERS:
        exists = session.execute(
            select(InboundOrder.id).where(InboundOrder.no == no)
        ).first()
        if exists:
            stats["skipped"] += 1
            continue

        sku_type = _SKU_TYPE[otype]
        sku_id = _sku_id(session, sku_type, sku_code)
        loc_id = session.execute(
            select(Location.id).where(Location.code == loc_code)
        ).scalar_one()
        sup_id = None
        if sup_code:
            sup_id = session.execute(
                select(Supplier.id).where(Supplier.code == sup_code)
            ).scalar_one()

        when = _utcnow() - timedelta(days=days_ago)
        order = InboundOrder(
            no=no, type=otype, supplier_id=sup_id,
            status=str(OrderStatus.DONE), plan_qty=qty, actual_qty=qty,
            creator_id=1, checker_id=1,
            finished_at=when,
            created_at=when,          # 显式给值才能盖过 server_default
        )
        session.add(order)
        session.flush()
        session.add(InboundItem(order_id=order.id, sku_id=sku_id, qty=qty,
                                location_id=loc_id))

        # 唯一合法的库存写入入口：写 inventory + txn（行锁、锁序统一）
        apply_many(
            session,
            [Move(sku_type, sku_id, loc_id, qty)],
            biz_type=_BIZ_TYPE[otype],
            biz_no=no,
            operator_id=1,
        )
        stats["order"] += 1

        # apply_many 不接受时间参数，txn.created_at 由 server_default 填成 now，
        # 这里只回填时间戳（不动 qty/balance），让流水看起来是历史发生的。
        session.flush()
        session.execute(update(Txn).where(Txn.biz_no == no).values(created_at=when))
        stats["txn"] += 1

    session.commit()
    return stats


def main() -> int:
    with SessionLocal() as s:
        stats = seed_demo(s)
    print(f"seed_demo done: {stats}")
    if stats["order"] == 0:
        print("演示单已存在，未重复写入。")
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
