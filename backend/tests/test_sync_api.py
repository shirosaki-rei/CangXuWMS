# -*- coding: utf-8 -*-
"""离线补传测试（T-02-4，接口 58 / 接口文档 3.8）。

覆盖：逐条执行与逐条返回、单条失败不影响后续（BR-012）、
幂等（op_log 兜底）、op_type 白名单、批量上限、按 created_at 排序。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.domain.models import Inventory, Location, OutboundItem, OutboundOrder, Product
from app.domain.stock import Move, apply_many

from tests.conftest import login


def _post(client, path, headers, json=None):
    return client.post(path, headers={**headers, "X-Client-Op-Id": str(uuid.uuid4())},
                       json=json)


@pytest.fixture
def ah(client):
    return login(client, "admin")


@pytest.fixture
def kh(client):
    return login(client, "wangjf")


@pytest.fixture
def stocked(seeded, wh1_id, wh1_location_id):
    """铺 40 件 A3288 到 WH-001 第一个库位，并取销售出库单。"""
    with SessionLocal() as s:
        oid = s.execute(select(OutboundOrder.id).where(
            OutboundOrder.no == "SO20260127001")).scalar_one()
        sku = s.execute(select(Product.id).where(Product.code == "A3288")).scalar_one()
        apply_many(s, [Move("PRODUCT", sku, wh1_location_id, 40)],
                   biz_type="PURCHASE_IN", biz_no="SYNC-SEED", operator_id=1)
        s.commit()
    return {"order_id": oid, "sku_id": sku, "location_id": wh1_location_id}


def _stock(sku_id: int) -> int:
    with SessionLocal() as s:
        return int(s.execute(
            select(func.coalesce(func.sum(Inventory.qty), 0)).where(
                Inventory.sku_type == "PRODUCT", Inventory.sku_id == sku_id)
        ).scalar())


def _picked(order_id: int, status: str = "PICKED") -> int:
    """已拣未发的行数。注意 pick 只记录意图，不扣库存——扣减在 submit。"""
    with SessionLocal() as s:
        return int(s.execute(select(func.count()).select_from(OutboundItem).where(
            OutboundItem.order_id == order_id, OutboundItem.status == status)).scalar())


def _push(client, headers, ops):
    return _post(client, "/api/v1/sync/push", headers, {"ops": ops})


def _op(op_type, order_id, body, op_id=None, created_at=None):
    return {
        "client_op_id": op_id or str(uuid.uuid4()),
        "op_type": op_type,
        "path": f"/api/v1/outbound-orders/{order_id}/pick",
        "body": {"order_id": order_id, **body},
        "created_at": created_at,
    }


# ---------------------------------------------------------------- 基本行为
def test_补传拣货并扣库存(stocked, client, kh):
    ops = [_op("OUTBOUND_PICK", stocked["order_id"],
               {"location_id": stocked["location_id"], "qty": 5},
               created_at="2026-11-03T10:00:00Z")]
    r = _push(client, kh, ops)
    d = r.json()["data"]
    assert d["total"] == 1
    assert d["results"][0]["status"] == "OK"
    # pick 只落明细不扣库存，扣减在 submit
    assert _picked(stocked["order_id"]) == 5
    assert _stock(stocked["sku_id"]) == 40


def test_补传提交(stocked, client, kh):
    _push(client, kh, [_op("OUTBOUND_PICK", stocked["order_id"],
                           {"location_id": stocked["location_id"], "qty": 20},
                           created_at="2026-11-03T10:00:00Z")])
    r = _push(client, kh, [_op("OUTBOUND_SUBMIT", stocked["order_id"], {},
                               created_at="2026-11-03T10:01:00Z")])
    assert r.json()["data"]["results"][0]["status"] == "OK"
    assert _stock(stocked["sku_id"]) == 20


def test_按created_at升序执行(stocked, client, kh):
    """乱序传入也要按扫码时间先后执行，否则后扫的反而先落库。"""
    ops = [
        _op("OUTBOUND_PICK", stocked["order_id"],
            {"location_id": stocked["location_id"], "qty": 10},
            op_id="sync-order-2", created_at="2026-11-03T10:05:00Z"),
        _op("OUTBOUND_PICK", stocked["order_id"],
            {"location_id": stocked["location_id"], "qty": 5},
            op_id="sync-order-1", created_at="2026-11-03T10:00:00Z"),
    ]
    r = _push(client, kh, ops)
    results = r.json()["data"]["results"]
    assert [x["client_op_id"] for x in results] == ["sync-order-1", "sync-order-2"]
    assert all(x["status"] == "OK" for x in results)
    assert _picked(stocked["order_id"]) == 15, "5 + 10 按时间顺序都落库了"


# ---------------------------------------------------------------- 幂等
def test_重复补传返回DUPLICATE(stocked, client, kh):
    op = _op("OUTBOUND_PICK", stocked["order_id"],
             {"location_id": stocked["location_id"], "qty": 5},
             op_id="sync-dup-0001", created_at="2026-11-03T10:00:00Z")
    assert _push(client, kh, [op]).json()["data"]["results"][0]["status"] == "OK"

    r = _push(client, kh, [op])
    res = r.json()["data"]["results"][0]
    assert res["status"] == "DUPLICATE"
    assert res["http_code"] == "WMS-4091"
    assert _picked(stocked["order_id"]) == 5, "不能落两次库"


def test_Redis键丢了我有op_log兜底(stocked, client, kh):
    """接口 1.3 第 5 条：Redis 键过期后的重放由 DB 唯一索引兜底。"""
    from app.core.redis import rds

    op = _op("OUTBOUND_PICK", stocked["order_id"],
             {"location_id": stocked["location_id"], "qty": 5},
             op_id="sync-dbfallback", created_at="2026-11-03T10:00:00Z")
    _push(client, kh, [op])
    rds.delete("idem:sync-dbfallback")  # 模拟 Redis 键过期

    r = _push(client, kh, [op])
    assert r.json()["data"]["results"][0]["status"] == "DUPLICATE"
    assert _picked(stocked["order_id"]) == 5


# ---------------------------------------------------------------- 冲突处置
def test_单条失败不影响后续_BR012(stocked, client, kh):
    """库存不足的那条 FAILED，后面的照常执行。"""
    ops = [
        _op("OUTBOUND_PICK", stocked["order_id"],
            {"location_id": stocked["location_id"], "qty": 5},
            op_id="sync-ok-1", created_at="2026-11-03T10:00:00Z"),
        # 这条要失败：库位只有 35 可用，拣 999
        _op("OUTBOUND_PICK", stocked["order_id"],
            {"location_id": stocked["location_id"], "qty": 999},
            op_id="sync-fail-1", created_at="2026-11-03T10:01:00Z"),
        _op("OUTBOUND_PICK", stocked["order_id"],
            {"location_id": stocked["location_id"], "qty": 5},
            op_id="sync-ok-2", created_at="2026-11-03T10:02:00Z"),
    ]
    r = _push(client, kh, ops)
    results = r.json()["data"]["results"]
    assert [x["status"] for x in results] == ["OK", "FAILED", "OK"]
    assert results[1]["http_code"] == "WMS-4222"
    assert "不足" in results[1]["message"]
    assert _picked(stocked["order_id"]) == 10, "只有两条成功的落库"


def test_失败项可重试(stocked, client, kh):
    """失败不落 op_log、不占 Redis 键，客户端重试能真正重跑。"""
    bad = _op("OUTBOUND_PICK", stocked["order_id"],
              {"location_id": stocked["location_id"], "qty": 999},
              op_id="sync-retry-1", created_at="2026-11-03T10:00:00Z")
    assert _push(client, kh, [bad]).json()["data"]["results"][0]["status"] == "FAILED"

    good = {**bad, "body": {**bad["body"], "qty": 5}}
    r = _push(client, kh, [good])
    assert r.json()["data"]["results"][0]["status"] == "OK"
    assert _picked(stocked["order_id"]) == 5


def test_终态单据返回已关闭(stocked, client, ah, kh):
    with SessionLocal() as s:
        o = s.get(OutboundOrder, stocked["order_id"])
        o.status = "DONE"
        s.commit()
    r = _push(client, kh, [_op("OUTBOUND_PICK", stocked["order_id"],
                               {"location_id": stocked["location_id"], "qty": 1},
                               created_at="2026-11-03T10:00:00Z")])
    res = r.json()["data"]["results"][0]
    assert res["status"] == "FAILED"
    assert res["http_code"] == "WMS-4092"


# ---------------------------------------------------------------- 白名单与上限
def test_不支持的op_type被拒(stocked, client, kh):
    ops = [{**_op("OUTBOUND_PICK", stocked["order_id"],
                  {"location_id": stocked["location_id"], "qty": 1}),
            "op_type": "DROP_TABLE"}]
    r = _push(client, kh, ops)
    res = r.json()["data"]["results"][0]
    assert res["status"] == "FAILED"
    assert "不支持" in res["message"]


def test_body缺少单据id被拒(stocked, client, kh):
    ops = [{"client_op_id": str(uuid.uuid4()), "op_type": "OUTBOUND_PICK",
            "path": "/x", "body": {}, "created_at": None}]
    r = _push(client, kh, ops)
    assert r.json()["data"]["results"][0]["status"] == "FAILED"


def test_超过50条被拒(stocked, client, kh):
    ops = [_op("OUTBOUND_PICK", stocked["order_id"],
               {"location_id": stocked["location_id"], "qty": 1})
           for _ in range(51)]
    r = _push(client, kh, ops)
    assert r.json()["code"] == "WMS-4221"
    assert r.json()["data"]["limit"] == 50


def test_空ops被拒(client, kh):
    r = _push(client, kh, [])
    assert r.status_code == 400


def test_未登录不能补传(client):
    """带合法 body 与幂等键但无 token：必须 401。"""
    r = client.post("/api/v1/sync/push",
                    headers={"X-Client-Op-Id": "no-auth-0001"},
                    json={"ops": [{
                        "client_op_id": "no-auth-0002", "op_type": "OUTBOUND_PICK",
                        "path": "/x", "body": {"order_id": 1}, "created_at": None,
                    }]})
    assert r.status_code == 401
