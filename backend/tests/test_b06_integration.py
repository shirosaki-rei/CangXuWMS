# -*- coding: utf-8 -*-
"""B06 测试：集成推送（59/60/61）、幂等重放、对账任务、Gate 检查。"""
from __future__ import annotations

import json
import time
import uuid

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.integration_auth import sign
from app.domain.models import InboundOrder, OutboundOrder, ReconcileDiff
from app.domain.stock import Move, apply_many
from app.tasks import reconcile

APP_KEY = "mes-prod"
APP_SECRET = "mes-secret-change-me"


def _headers(body: bytes) -> dict:
    ts = int(time.time())
    return {
        "Content-Type": "application/json; charset=utf-8",
        "X-App-Key": APP_KEY,
        "X-Timestamp": str(ts),
        "X-Sign": sign(APP_SECRET, APP_KEY, str(ts), body),
    }


def _push(client, path: str, payload: dict):
    raw = json.dumps(payload).encode()
    return client.post(f"/api/v1/integration{path}", content=raw, headers=_headers(raw))


# ---------------------------------------------------------------- 59
def test_推送销售发货生成出库单(seeded, client):
    body = {"no": "SO20260201001", "version": 1, "sales_order_no": "XSDD20260201001",
            "product_code": "A3288", "plan_qty": 20}
    r = _push(client, "/outbound-orders", body)
    assert r.json()["code"] == "0", r.text
    oid = r.json()["data"]["id"]
    with SessionLocal() as s:
        o = s.get(OutboundOrder, oid)
        assert o.type == "SALES" and o.status == "PENDING" and o.plan_qty == 20


def test_销售发货重复推送返回首次结果(seeded, client):
    body = {"no": "SO20260201002", "version": 1, "product_code": "A3288", "plan_qty": 5}
    first = _push(client, "/outbound-orders", body).json()["data"]["id"]
    again = _push(client, "/outbound-orders", body).json()
    assert again["code"] == "WMS-4091"
    assert again["data"]["id"] == first


def test_产品编码未维护被拒(seeded, client):
    r = _push(client, "/outbound-orders",
              {"no": "SO20260201003", "version": 1, "product_code": "NOPE", "plan_qty": 1})
    assert r.json()["code"] == "WMS-4001"


# ---------------------------------------------------------------- 60
def test_推送领料需求生成领料单(seeded, client):
    body = {"no": "PL20260201001", "version": 1, "task_no": "RWD20260201001",
            "items": [{"material_code": "BAT-LIPO-4500-003", "qty": 120},
                      {"material_code": "PCB-MAIN-V3", "qty": 30}]}
    r = _push(client, "/pick-requests", body)
    assert r.json()["code"] == "0", r.text
    with SessionLocal() as s:
        o = s.get(OutboundOrder, r.json()["data"]["id"])
        assert o.type == "PICK" and o.plan_qty == 150


# ---------------------------------------------------------------- 61
def test_推送完工入库生成产品入库单(seeded, client):
    body = {"no": "PI20260201001", "version": 1, "task_no": "RWD20260201001",
            "box_code": "BOX20260201XYZ", "product_code": "A3288", "qty": 100}
    r = _push(client, "/production-inbound", body)
    assert r.json()["code"] == "0", r.text
    with SessionLocal() as s:
        o = s.get(InboundOrder, r.json()["data"]["id"])
        assert o.type == "PRODUCT" and o.plan_qty == 100


def test_完工入库重复推送不产生重复单据(seeded, client):
    body = {"no": "PI20260201002", "version": 1, "product_code": "A3288", "qty": 10}
    _push(client, "/production-inbound", body)
    r = _push(client, "/production-inbound", body)
    assert r.json()["code"] == "WMS-4091"
    with SessionLocal() as s:
        n = s.execute(select(InboundOrder).where(
            InboundOrder.no == "PI20260201002")).scalars().all()
        assert len(n) == 1


def test_集成接口仍需签名(seeded, client):
    r = client.post("/api/v1/integration/outbound-orders",
                    json={"no": "SO-X", "version": 1, "product_code": "A3288", "plan_qty": 1})
    assert r.status_code == 401


# ---------------------------------------------------------------- 对账
def test_对账发现库存与流水不一致(seeded, wh1_id, wh1_location_id):
    """直接改 inventory.qty 绕过 stock.apply，模拟「有人在流水之外改了库存」。"""
    with SessionLocal() as s:
        apply_many(s, [Move("MATERIAL", 1, wh1_location_id, 10)],
                   biz_type="PURCHASE_IN", biz_no="RC-1", operator_id=1)
        s.commit()
        # 制造不一致
        from app.domain.models import Inventory
        inv = s.execute(select(Inventory).where(
            Inventory.location_id == wh1_location_id)).scalar_one()
        inv.qty += 5
        s.commit()

    with SessionLocal() as s:
        result = reconcile.run(s)
        assert result["diffs"] >= 1
        diffs = s.execute(select(ReconcileDiff)).scalars().all()
        assert diffs, "应写入 reconcile_diff"
        assert any(d.diff_type == "QTY" for d in diffs)


def test_对账一致时无差异(seeded, wh1_location_id):
    with SessionLocal() as s:
        apply_many(s, [Move("MATERIAL", 1, wh1_location_id, 10)],
                   biz_type="PURCHASE_IN", biz_no="RC-2", operator_id=1)
        s.commit()
    with SessionLocal() as s:
        result = reconcile.run(s)
    assert result["diffs"] == 0


# ---------------------------------------------------------------- Gate
def test_gate检查能跑(seeded):
    from tools.gate_check import check

    ok, lines = check()
    assert len(lines) >= 3
    assert any(l.startswith("G1") for l in lines)
