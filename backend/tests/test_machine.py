# -*- coding: utf-8 -*-
"""domain/machine.py 状态机单测（T-00-7 交付物）。"""
from __future__ import annotations

import pytest

from app.core.errors import BizError, Codes
from app.domain.machine import (
    TERMINAL,
    TRANSITIONS,
    advance_by_qty,
    can_transit,
    is_terminal,
    known,
    transit,
)


def test_五类单据都已登记():
    assert set(TRANSITIONS) == {"INBOUND", "OUTBOUND", "INSPECTION", "STOCKTAKE", "MOVE"}
    assert set(TERMINAL) == set(TRANSITIONS)


@pytest.mark.parametrize("doc,cur,nxt", [
    ("INBOUND", "PENDING", "PARTIAL"),
    ("INBOUND", "PENDING", "DONE"),
    ("INBOUND", "PARTIAL", "DONE"),
    ("INBOUND", "PENDING", "VOID"),
    ("INBOUND", "PARTIAL", "VOID"),
    ("OUTBOUND", "PENDING", "PARTIAL"),
    ("OUTBOUND", "PARTIAL", "VOID"),
    ("INSPECTION", "PENDING", "CHECKING"),
    ("INSPECTION", "CHECKING", "DONE"),
    ("STOCKTAKE", "PENDING", "COUNTING"),
    ("STOCKTAKE", "COUNTING", "CONFIRMING"),
    ("STOCKTAKE", "CONFIRMING", "DONE"),
    ("MOVE", "PENDING", "DOING"),
    ("MOVE", "DOING", "DONE"),
])
def test_合法迁移(doc, cur, nxt):
    assert can_transit(doc, cur, nxt)
    assert transit(doc, cur, nxt, reason="x" if nxt == "VOID" else None) == nxt


@pytest.mark.parametrize("doc,cur,nxt", [
    ("INBOUND", "PENDING", "CHECKING"),      # 跨类型
    ("INSPECTION", "PENDING", "DONE"),       # 不能跳过检验中
    ("STOCKTAKE", "PENDING", "DONE"),        # 不能跳过盘点中/待确认
    ("STOCKTAKE", "CONFIRMING", "COUNTING"),
])
def test_非法迁移抛4221(doc, cur, nxt):
    assert not can_transit(doc, cur, nxt)
    with pytest.raises(BizError) as e:
        transit(doc, cur, nxt)
    assert e.value.code == Codes.BIZ_RULE


@pytest.mark.parametrize("doc,cur,nxt", [
    ("INBOUND", "DONE", "PENDING"),          # 终态回退
    ("INBOUND", "VOID", "DONE"),             # 作废后不能再完成
    ("INBOUND", "DONE", "VOID"),             # 终态再作废
    ("OUTBOUND", "DONE", "PARTIAL"),
    ("INSPECTION", "DONE", "CHECKING"),
    ("MOVE", "DONE", "DOING"),
])
def test_终态不可回退抛4092(doc, cur, nxt):
    assert not can_transit(doc, cur, nxt)
    with pytest.raises(BizError) as e:
        transit(doc, cur, nxt)
    assert e.value.code == Codes.ORDER_CLOSED


def test_终态集合():
    assert is_terminal("INBOUND", "DONE") and is_terminal("INBOUND", "VOID")
    assert not is_terminal("INBOUND", "PARTIAL")
    assert is_terminal("STOCKTAKE", "CANCELED")
    assert is_terminal("MOVE", "DONE")


def test_同态直接返回不报错():
    assert transit("INBOUND", "PENDING", "PENDING") == "PENDING"


def test_作废必须填原因():
    with pytest.raises(BizError) as e:
        transit("INBOUND", "PENDING", "VOID", reason="   ")
    assert e.value.code == Codes.BAD_REQUEST


def test_未登记单据类型报5000():
    assert not known("UNKNOWN")
    with pytest.raises(BizError) as e:
        transit("UNKNOWN", "A", "B")
    assert e.value.code == Codes.SERVER_ERROR


@pytest.mark.parametrize("done,plan,expect", [
    (100, 100, "DONE"),
    (120, 100, "DONE"),   # 超收也走完成，超收比例由校验 R4 管
    (12, 100, "PARTIAL"),
    (0, 0, "DONE"),
])
def test_按数量推进(done, plan, expect):
    assert advance_by_qty("INBOUND", "PENDING", done, plan) == expect


def test_数量推进不适用于非出入库单():
    with pytest.raises(BizError):
        advance_by_qty("STOCKTAKE", "PENDING", 1, 1)
