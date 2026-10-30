# -*- coding: utf-8 -*-
"""库存并发守恒（架构 9.4 门槛：10 线程同 SKU 加减，断言总数守恒）。

只在 MySQL 下运行——SQLite 没有行锁，跑这个用例是自欺欺人。
"""
from __future__ import annotations

import threading

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.domain.enums import BizType, SkuType
from app.domain.models import Inventory, Txn
from app.domain.stock import Move, apply_many

THREADS = 10
OPS_PER_THREAD = 5
STEP = 7
LOC = 777001
SKU = 777001


@pytest.mark.requires_mysql
def test_十线程加减库存守恒(mysql_only):
    # 铺底：先入 1000
    with SessionLocal() as s:
        apply_many(s, [Move(str(SkuType.PRODUCT), SKU, LOC, 1000)],
                   biz_type=BizType.PURCHASE_IN, biz_no="CONC-SEED", operator_id=0)
        s.commit()

    errors: list[Exception] = []
    barrier = threading.Barrier(THREADS)

    def worker(idx: int) -> None:
        try:
            barrier.wait()
            for i in range(OPS_PER_THREAD):
                # 偶数线程加、奇数线程减，总额必须守恒
                delta = STEP if idx % 2 == 0 else -STEP
                with SessionLocal() as s:
                    apply_many(s, [Move(str(SkuType.PRODUCT), SKU, LOC, delta)],
                               biz_type=BizType.MOVE, biz_no=f"CONC-{idx}-{i}", operator_id=idx)
                    s.commit()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发写入出现异常：{errors[:3]}"

    with SessionLocal() as s:
        qty = s.execute(
            select(Inventory.qty).where(Inventory.sku_id == SKU, Inventory.location_id == LOC)
        ).scalar_one()
        txn_sum = s.execute(
            select(func.coalesce(func.sum(Txn.qty_delta), 0)).where(Txn.sku_id == SKU)
        ).scalar()
        txn_count = s.execute(
            select(func.count()).select_from(Txn).where(Txn.sku_id == SKU)
        ).scalar()

    assert qty == 1000, f"库存应为铺底值 1000，实际 {qty}"
    assert int(txn_sum) == 1000, f"流水合计应等于库存，实际 {txn_sum}"
    assert txn_count == 1 + THREADS * OPS_PER_THREAD, f"流水条数不符：{txn_count}"


@pytest.mark.requires_mysql
def test_并发下可用量不会被击穿(mysql_only):
    """10 个线程同时扣 1 件，只有 qty 件能成功。"""
    from app.core.errors import BizError

    start = 5
    with SessionLocal() as s:
        apply_many(s, [Move(str(SkuType.PRODUCT), 777002, 777002, start)],
                   biz_type=BizType.PURCHASE_IN, biz_no="SHORT-SEED", operator_id=0)
        s.commit()

    ok, rejected = [], []
    barrier = threading.Barrier(THREADS)

    def worker(idx: int) -> None:
        barrier.wait()
        try:
            with SessionLocal() as s:
                apply_many(s, [Move(str(SkuType.PRODUCT), 777002, 777002, -1)],
                           biz_type=BizType.SALES_OUT, biz_no=f"SHORT-{idx}", operator_id=idx)
                s.commit()
            ok.append(idx)
        except BizError as e:
            if e.code == "WMS-4222":
                rejected.append(idx)
            else:
                raise

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(ok) == start, f"应恰好 {start} 笔成功，实际 {len(ok)}"
    assert len(rejected) == THREADS - start
    with SessionLocal() as s:
        qty = s.execute(
            select(Inventory.qty).where(Inventory.sku_id == 777002, Inventory.location_id == 777002)
        ).scalar_one()
    assert qty == 0, f"库存不应为负，实际 {qty}"
