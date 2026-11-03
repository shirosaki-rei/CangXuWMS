# -*- coding: utf-8 -*-
"""入库闭环测试（T-01-3/4/6，接口 7/8/26/27/37，页面 P05–P09）。

覆盖：扫码查重（BR-010）、库位类型（BR-013）、状态推进、提交落库与库存守恒、
作废冲销（BR-002）、差异原因必填（BR-016）、检验关联（BR-004）。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.domain.enums import LocationStatus, LocationType, OrderStatus
from app.domain.models import (
    InboundItem,
    InboundOrder,
    Inventory,
    Location,
    Material,
    Txn,
)
from app.domain.stock import Move, apply_many

from tests.conftest import login


def _post(client, path, headers, json=None):
    """写操作统一带 X-Client-Op-Id，否则会被幂等中间件挡在 4001。"""
    return client.post(path, headers={**headers, "X-Client-Op-Id": str(uuid.uuid4())},
                       json=json)


@pytest.fixture
def ah(client):
    return login(client, "admin")


@pytest.fixture
def kh(client):
    return login(client, "wangjf")


@pytest.fixture
def pr_order(seeded, wh1_id, wh1_location_id):
    """种子里的采购入库单 PR20260127001（关联已检合格的检验单）。"""
    with SessionLocal() as s:
        oid = s.execute(select(InboundOrder.id).where(
            InboundOrder.no == "PR20260127001")).scalar_one()
        sku = s.execute(select(InboundItem.sku_id).where(
            InboundItem.order_id == oid)).scalar_one()
    return {"order_id": oid, "sku_id": sku, "warehouse_id": wh1_id,
            "location_id": wh1_location_id}


def _stock(sku_id: int, sku_type: str = "MATERIAL") -> int:
    with SessionLocal() as s:
        return int(s.execute(
            select(func.coalesce(func.sum(Inventory.qty), 0)).where(
                Inventory.sku_type == sku_type, Inventory.sku_id == sku_id)
        ).scalar())


def _txn_count(biz_no: str) -> int:
    with SessionLocal() as s:
        return int(s.execute(select(func.count()).select_from(Txn).where(
            Txn.biz_no == biz_no)).scalar())


def _scan(client, kh, order_id, box=None, sn=None, loc=None, qty=1):
    return _post(client, f"/api/v1/inbound-orders/{order_id}/scan", kh,
                 {"box_code": box, "sn": sn, "location_id": loc, "qty": qty})


# ---------------------------------------------------------------- 列表与详情
def test_入库单列表与筛选(pr_order, client, ah):
    d = client.get("/api/v1/inbound-orders", headers=ah).json()["data"]
    assert d["total"] == 1
    assert d["items"][0]["no"] == "PR20260127001"
    assert d["items"][0]["type_label"] == "采购入库"
    assert d["items"][0]["status_label"] == "待入库"

    assert client.get("/api/v1/inbound-orders?type=PRODUCT",
                      headers=ah).json()["data"]["total"] == 0
    assert client.get("/api/v1/inbound-orders?status=DONE",
                      headers=ah).json()["data"]["total"] == 0


def test_四类Tab角标(pr_order, client, ah):
    d = client.get("/api/v1/inbound-orders/status-counts", headers=ah).json()["data"]
    assert d["PURCHASE"]["PENDING"] == 1


def test_入库单详情带明细(pr_order, client, ah):
    d = client.get(f"/api/v1/inbound-orders/{pr_order['order_id']}",
                   headers=ah).json()["data"]
    assert d["no"] == "PR20260127001"
    assert len(d["items"]) == 1
    # 采购入库单的 SKU 必须是物料编码，不能撞上同 id 的成品
    assert d["items"][0]["sku_code"] == "DSP-AMOLED-67-FULL"
    assert d["plan_qty"] == 200 and d["actual_qty"] == 0
    assert d["qty_mismatch"] is True, "实收 0 ≠ 计划 200"
    assert d["terminal"] is False


def test_详情不存在报4001(client, ah):
    r = client.get("/api/v1/inbound-orders/999999", headers=ah)
    assert r.json()["code"] == "WMS-4001"


# ---------------------------------------------------------------- 扫码收货
def test_扫码追加明细并推进部分入库(pr_order, client, kh):
    r = _scan(client, kh, pr_order["order_id"], box="BOX20260127ABC123456",
              loc=pr_order["location_id"], qty=120)
    d = r.json()["data"]
    assert d["scanned"] == 120 and d["plan_qty"] == 200
    assert d["status"] == "PARTIAL", "120 < 200 应为部分入库"
    assert d["duplicate"] is False


def test_箱码重复被拒_WMS4093(pr_order, client, kh):
    assert _scan(client, kh, pr_order["order_id"], box="BOX-DUP",
                 loc=pr_order["location_id"]).json()["code"] == "0"
    r = _scan(client, kh, pr_order["order_id"], box="BOX-DUP",
              loc=pr_order["location_id"])
    assert r.json()["code"] == "WMS-4093"
    assert r.json()["data"]["duplicate"] is True


def test_同一SN不能挂两张未关闭单据_BR010(pr_order, client, kh):
    oid = pr_order["order_id"]
    for i in (1, 2):
        assert _scan(client, kh, oid, sn=f"SN-BR10-{i}",
                     loc=pr_order["location_id"]).json()["code"] == "0"

    with SessionLocal() as s:
        mat = s.execute(select(Material.id).limit(1)).scalar_one()
        o2 = InboundOrder(no="PR20260127002", type="PURCHASE", source_no="JY20260127002",
                          status="PENDING", plan_qty=10, actual_qty=0, creator_id=1)
        s.add(o2)
        s.flush()
        s.add(InboundItem(order_id=o2.id, sku_id=mat, qty=0))
        s.commit()
        oid2 = o2.id

    r = _scan(client, kh, oid2, sn="SN-BR10-1", loc=pr_order["location_id"])
    assert r.json()["code"] == "WMS-4093"
    assert "BR-010" in r.json()["message"]


def test_危品库位不能放普通物料_BR013(pr_order, client, kh):
    """BR-013 是单向规则：危品库位只能存放危品物料。"""
    with SessionLocal() as s:
        # PCB-MAIN-V3 是普通物料
        normal_sku = s.execute(select(Material.id).where(
            Material.code == "PCB-MAIN-V3")).scalar_one()
        danger_loc = s.execute(select(Location.id).where(
            Location.type == str(LocationType.DANGEROUS)).limit(1)).scalar_one()
        o = InboundOrder(no="PR20260127003", type="PURCHASE", source_no="JY20260127002",
                         status="PENDING", plan_qty=10, actual_qty=0, creator_id=1)
        s.add(o)
        s.flush()
        s.add(InboundItem(order_id=o.id, sku_id=normal_sku, qty=0))
        s.commit()
        oid = o.id

    r = _scan(client, kh, oid, box="BOX-DANGER-1", loc=danger_loc, qty=5)
    assert r.json()["code"] == "WMS-4221"
    assert "危品" in r.json()["message"]


def test_危品物料可以上普通库位(pr_order, client, kh):
    """规则只约束「危品库位」，不禁止危品物料进普通库位。"""
    with SessionLocal() as s:
        glue = s.execute(select(Material.id).where(
            Material.code == "SOL-IPA-99")).scalar_one()
        normal_loc = s.execute(select(Location.id).where(
            Location.type == str(LocationType.NORMAL)).limit(1)).scalar_one()
        o = InboundOrder(no="PR20260127004", type="PURCHASE", source_no="JY20260127002",
                         status="PENDING", plan_qty=10, actual_qty=0, creator_id=1)
        s.add(o)
        s.flush()
        s.add(InboundItem(order_id=o.id, sku_id=glue, qty=0))
        s.commit()
        oid = o.id

    r = _scan(client, kh, oid, box="BOX-DANGER-OK", loc=normal_loc, qty=5)
    assert r.json()["code"] == "0"


def test_锁定库位不能上架(pr_order, client, kh):
    with SessionLocal() as s:
        loc = s.execute(select(Location).where(
            Location.status == str(LocationStatus.IDLE)).limit(1)).scalar_one()
        loc.status = str(LocationStatus.LOCKED)
        s.commit()
        lid = loc.id
    r = _scan(client, kh, pr_order["order_id"], box="BOX-LOCKED-1", loc=lid)
    assert r.json()["code"] == "WMS-4221"
    assert "锁定" in r.json()["message"]


def test_未指定库位被拒(pr_order, client, kh):
    r = _scan(client, kh, pr_order["order_id"], box="BOX-NOLOC")
    assert r.json()["code"] == "WMS-4001"
    assert "库位" in r.json()["message"]


def test_箱码与SN都为空被拒(pr_order, client, kh):
    r = _scan(client, kh, pr_order["order_id"], loc=pr_order["location_id"])
    assert r.json()["code"] == "WMS-4001"


def test_终态单据不能再扫码(pr_order, client, kh):
    with SessionLocal() as s:
        o = s.get(InboundOrder, pr_order["order_id"])
        o.status = str(OrderStatus.DONE)
        s.commit()
    r = _scan(client, kh, pr_order["order_id"], box="BOX-TERMINAL",
              loc=pr_order["location_id"])
    assert r.json()["code"] == "WMS-4092"


# ---------------------------------------------------------------- 提交落库
def test_提交入库落库存并写流水(pr_order, client, kh):
    sku = pr_order["sku_id"]
    assert _stock(sku) == 0

    # 分两批扫码：120 + 80 = 200 = 计划数。扫码只推进到 PARTIAL，DONE 由 submit 独占
    for i, qty in enumerate((120, 80)):
        r = _scan(client, kh, pr_order["order_id"], box=f"BOX-SUBMIT-{i}",
                  loc=pr_order["location_id"], qty=qty)
        assert r.json()["data"]["status"] == "PARTIAL", i

    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/submit", kh, {})
    d = r.json()["data"]
    assert d["status"] == "DONE" and d["actual_qty"] == 200
    assert d["finished_at"] is not None

    assert _stock(sku) == 200
    with SessionLocal() as s:
        rows = s.execute(select(Inventory).where(Inventory.sku_id == sku)).scalars().all()
        assert len(rows) == 1 and rows[0].qty == 200
        assert rows[0].location_id == pr_order["location_id"]
    assert _txn_count("PR20260127001") == 1


def test_没有扫码记录不能提交(pr_order, client, kh):
    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/submit", kh, {})
    assert r.json()["code"] == "WMS-4221"
    assert "扫码" in r.json()["message"]


def test_实收与计划不一致必须填原因_BR016(pr_order, client, kh):
    _scan(client, kh, pr_order["order_id"], box="BOX-DIFF",
          loc=pr_order["location_id"], qty=150)
    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/submit", kh, {})
    assert r.json()["code"] == "WMS-4001"
    assert "差异原因" in r.json()["message"]

    assert _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/submit", kh,
                 {"reason": "短"}).json()["code"] == "WMS-4001"

    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/submit", kh,
              {"reason": "来料短少，供应商确认少发 50 件"})
    assert r.json()["code"] == "0"
    assert _stock(pr_order["sku_id"]) == 150


def test_有明细未指定库位不能提交(pr_order, client, kh):
    """扫过码的明细必须带上架库位；qty=0 的占位行不参与校验。"""
    with SessionLocal() as s:
        s.add(InboundItem(order_id=pr_order["order_id"], sku_id=pr_order["sku_id"],
                          box_code="BOX-NULLLOC", qty=50, location_id=None))
        s.commit()
    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/submit", kh, {})
    assert r.json()["code"] == "WMS-4221"
    assert "库位" in r.json()["message"]


def test_占位行不参与提交校验(pr_order, client, kh):
    """种子带的 qty=0 占位行不该让提交失败。"""
    _scan(client, kh, pr_order["order_id"], box="BOX-PLACEHOLDER",
          loc=pr_order["location_id"], qty=200)
    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/submit", kh, {})
    assert r.json()["code"] == "0"
    assert _stock(pr_order["sku_id"]) == 200


def test_采购入库必须关联已检合格检验单_BR004(pr_order, client, kh):
    with SessionLocal() as s:
        o = s.get(InboundOrder, pr_order["order_id"])
        o.source_no = None
        s.commit()
    # 扫满计划数，避开「差异原因必填」检查，才能验到 BR-004
    _scan(client, kh, pr_order["order_id"], box="BOX-BR004",
          loc=pr_order["location_id"], qty=200)
    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/submit", kh, {})
    assert r.json()["code"] == "WMS-4221"
    assert "BR-004" in r.json()["message"]


def test_提交是幂等的(pr_order, client, kh):
    _scan(client, kh, pr_order["order_id"], box="BOX-IDEM",
          loc=pr_order["location_id"], qty=200)
    op = "inbound-submit-idem-0001"
    path = f"/api/v1/inbound-orders/{pr_order['order_id']}/submit"
    r1 = client.post(path, headers={**kh, "X-Client-Op-Id": op}, json={})
    r2 = client.post(path, headers={**kh, "X-Client-Op-Id": op}, json={})
    assert r1.json()["code"] == "0"
    assert r2.json()["code"] == "WMS-4091"
    assert r2.json()["data"]["order_id"] == r1.json()["data"]["order_id"]
    assert _stock(pr_order["sku_id"]) == 200, "不能落两次库"


# ---------------------------------------------------------------- 作废
def test_作废必须填原因(pr_order, client, ah):
    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/void", ah,
              {"reason": "   "})
    assert r.json()["code"] == "WMS-4001"


def test_作废部分入库单会冲销库存_BR002(pr_order, client, kh, ah):
    """短收提交后单子是「部分入库」且已落库，作废必须把库存冲回去。"""
    sku = pr_order["sku_id"]
    _scan(client, kh, pr_order["order_id"], box="BOX-VOID",
          loc=pr_order["location_id"], qty=150)
    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/submit", kh,
              {"reason": "来料短少，先入已收部分"})
    assert r.json()["data"]["status"] == "PARTIAL"
    assert _stock(sku) == 150

    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/void", ah,
              {"reason": "MES 推送重复，主管确认作废"})
    assert r.json()["data"]["status"] == "VOID"
    assert _stock(sku) == 0, "作废后库存必须冲销归零"
    # 冲销也是流水，不是 DELETE（BR-002）
    assert _txn_count("PR20260127001") == 2


def test_已入库终态不可作废(pr_order, client, kh, ah):
    """PRD 第 9 章：已入库是终态，只能部分入库态作废。"""
    _scan(client, kh, pr_order["order_id"], box="BOX-FULL",
          loc=pr_order["location_id"], qty=200)
    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/submit", kh, {})
    assert r.json()["data"]["status"] == "DONE"
    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/void", ah,
              {"reason": "想作废一张已完成的单"})
    assert r.json()["code"] == "WMS-4092"


def test_终态不可再作废(pr_order, client, ah):
    with SessionLocal() as s:
        o = s.get(InboundOrder, pr_order["order_id"])
        o.status = str(OrderStatus.VOID)
        s.commit()
    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/void", ah,
              {"reason": "再作废一次"})
    assert r.json()["code"] == "WMS-4092"


# ---------------------------------------------------------------- 权限
def test_仓管员不能作废(pr_order, client, kh):
    r = _post(client, f"/api/v1/inbound-orders/{pr_order['order_id']}/void", kh,
              {"reason": "仓管员尝试作废"})
    assert r.status_code == 403
    assert r.json()["code"] == "WMS-4030"
