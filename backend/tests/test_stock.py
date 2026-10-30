# -*- coding: utf-8 -*-
"""domain/stock.py 单测（T-00-6 交付物）。

功能正确性在任何后端都能跑；真正的行锁竞争见 test_stock_concurrency.py（仅 MySQL）。
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.errors import BizError, Codes
from app.core.db import SessionLocal
from app.domain.enums import BizType, SkuType
from app.domain.models import Inventory, Txn
from app.domain.stock import Move, _merge, _retryable, apply_many, balance_of

P = SkuType.PRODUCT


def _qty(session, sku_id, location_id):
    return session.execute(
        select(Inventory.qty).where(
            Inventory.sku_type == str(P), Inventory.sku_id == sku_id,
            Inventory.location_id == location_id,
        )
    ).scalar_one_or_none()


def _run(unit):
    with SessionLocal() as s:
        out = unit(s)
        s.commit()
        return out


def test_合并同key变动():
    merged = _merge([Move("PRODUCT", 1, 10, 5), Move("PRODUCT", 1, 10, -2),
                     Move("PRODUCT", 1, 11, 3), Move("PRODUCT", 1, 11, 0)])
    assert len(merged) == 2
    assert {m.delta for m in merged} == {3, 3}


def test_零变动直接返回():
    def unit(s):
        return apply_many(s, [], biz_type=BizType.SALES_OUT, biz_no="X", operator_id=1)

    assert _run(unit) == []


def test_入库落库存并写流水():
    def unit(s):
        apply_many(s, [Move(str(P), 9001, 5001, 100)],
                   biz_type=BizType.PURCHASE_IN, biz_no="PR20260130001", operator_id=1)
        return _qty(s, 9001, 5001)

    assert _run(unit) == 100

    with SessionLocal() as s:
        txns = s.execute(
            select(Txn).where(Txn.sku_id == 9001, Txn.biz_no == "PR20260130001")
        ).scalars().all()
        assert len(txns) == 1
        assert txns[0].qty_delta == 100 and txns[0].balance == 100


def test_可用量不足报缺口():
    def unit(s):
        apply_many(s, [Move(str(P), 9002, 5002, 10)], biz_type=BizType.PURCHASE_IN,
                   biz_no="B1", operator_id=1)
        # locked 4 + frozen 3 → 可用 3
        inv = s.execute(select(Inventory).where(Inventory.sku_id == 9002)).scalar_one()
        inv.locked_qty, inv.frozen_qty = 4, 3
        s.flush()
        with pytest.raises(BizError) as e:
            apply_many(s, [Move(str(P), 9002, 5002, -5)], biz_type=BizType.SALES_OUT,
                       biz_no="B2", operator_id=1)
        raise e.value

    with pytest.raises(BizError) as exc:
        _run(unit)
    assert exc.value.code == Codes.STOCK_SHORT
    assert "缺口 2" in exc.value.message


def test_无库存行时减库存被拒():
    def unit(s):
        with pytest.raises(BizError) as e:
            apply_many(s, [Move(str(P), 9003, 5999, -1)], biz_type=BizType.SALES_OUT,
                       biz_no="B3", operator_id=1)
        assert e.value.code == Codes.STOCK_SHORT
        return True

    assert _run(unit)


def test_反向流水冲销不产生负数():
    def unit(s):
        apply_many(s, [Move(str(P), 9004, 5004, 50)], biz_type=BizType.PURCHASE_IN,
                   biz_no="B4", operator_id=1)
        apply_many(s, [Move(str(P), 9004, 5004, -20)], biz_type=BizType.VOID_REVERSE,
                   biz_no="B5", operator_id=1)
        return _qty(s, 9004, 5004)

    assert _run(unit) == 30


def test_同一事务多行多库位():
    def unit(s):
        apply_many(s, [Move(str(P), 9005, 5011, 10), Move(str(P), 9005, 5012, 20)],
                   biz_type=BizType.PURCHASE_IN, biz_no="B6", operator_id=1)
        return (_qty(s, 9005, 5011), _qty(s, 9005, 5012))

    assert _run(unit) == (10, 20)


def test_balance_of():
    def unit(s):
        apply_many(s, [Move(str(P), 9006, 5013, 7)], biz_type=BizType.PURCHASE_IN,
                   biz_no="B7", operator_id=1)
        return balance_of(s, str(P), 9006, 5013)

    assert _run(unit) == 7
    with SessionLocal() as s:
        assert balance_of(s, str(P), 999999, 5013) == 0


def test_流水总数守恒():
    """一次入库两次出库后，库存 = 入库 - 出库，流水条数 = 3。"""
    def unit(s):
        apply_many(s, [Move(str(P), 9007, 5014, 100)], biz_type=BizType.PURCHASE_IN,
                   biz_no="C1", operator_id=1)
        apply_many(s, [Move(str(P), 9007, 5014, -30)], biz_type=BizType.SALES_OUT,
                   biz_no="C2", operator_id=1)
        apply_many(s, [Move(str(P), 9007, 5014, -20)], biz_type=BizType.SALES_OUT,
                   biz_no="C3", operator_id=1)
        return _qty(s, 9007, 5014)

    assert _run(unit) == 50
    with SessionLocal() as s:
        n = s.execute(
            select(func.count()).select_from(Txn).where(Txn.sku_id == 9007)
        ).scalar()
        assert n == 3


@pytest.mark.parametrize("errno,expected", [
    (1213, True), (1062, True), (1045, False), (1146, False), (None, False),
])
def test_可重试错误判定(errno, expected):
    from sqlalchemy.exc import OperationalError

    exc = OperationalError("stmt", {}, Exception(errno) if errno else Exception("x"))
    assert _retryable(exc) is expected
