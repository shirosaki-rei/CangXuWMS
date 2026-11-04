# -*- coding: utf-8 -*-
"""出库闭环测试（T-02-1/2/3，接口 9/10/28/29/38，页面 P10–P13）。

覆盖：FIFO 推荐（BR-003）、SN 查重（BR-010）、可用量校验（R5）、
禁止超发、差异原因必填（BR-016）、提交扣减与库存守恒、作废冲销（BR-002）。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.domain.enums import OrderStatus
from app.domain.models import (
    Inventory,
    Location,
    Material,
    OutboundItem,
    OutboundOrder,
    Product,
    Txn,
)
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
def so_order(seeded, wh1_id, wh1_location_id):
    """种子里的销售出库单 SO20260127001（A3288，计划 20）。"""
    with SessionLocal() as s:
        oid = s.execute(select(OutboundOrder.id).where(
            OutboundOrder.no == "SO20260127001")).scalar_one()
        sku = s.execute(select(OutboundItem.sku_id).where(
            OutboundItem.order_id == oid)).scalar_one()
    return {"order_id": oid, "sku_id": sku, "location_id": wh1_location_id,
            "warehouse_id": wh1_id}


@pytest.fixture
def stocked(so_order):
    """给 A3288 在 WH-001 的两个库位铺库存，让 FIFO 有得可排。"""
    with SessionLocal() as s:
        locs = s.execute(
            select(Location.id).where(Location.warehouse_id == so_order["warehouse_id"])
            .order_by(Location.id).limit(2)
        ).scalars().all()
        # 早入库的放前面（FIFO 应该先推荐它）
        apply_many(s, [Move("PRODUCT", so_order["sku_id"], locs[0], 10)],
                   biz_type="PURCHASE_IN", biz_no="FIFO-EARLY", operator_id=1)
        apply_many(s, [Move("PRODUCT", so_order["sku_id"], locs[1], 30)],
                   biz_type="PURCHASE_IN", biz_no="FIFO-LATE", operator_id=1)
        s.commit()
        return {"early_loc": locs[0], "late_loc": locs[1]}


def _stock(sku_id: int, sku_type: str = "PRODUCT") -> int:
    with SessionLocal() as s:
        return int(s.execute(
            select(func.coalesce(func.sum(Inventory.qty), 0)).where(
                Inventory.sku_type == sku_type, Inventory.sku_id == sku_id)
        ).scalar())


def _txn_count(biz_no: str) -> int:
    with SessionLocal() as s:
        return int(s.execute(select(func.count()).select_from(Txn).where(
            Txn.biz_no == biz_no)).scalar())


# ---------------------------------------------------------------- 查询
def test_出库单列表与筛选(client, ah):
    d = client.get("/api/v1/outbound-orders", headers=ah).json()["data"]
    assert d["total"] == 2
    by_no = {i["no"]: i for i in d["items"]}
    assert by_no["SO20260127001"]["type_label"] == "销售出库"
    assert by_no["PL20260127001"]["type_label"] == "领料出库"
    assert by_no["SO20260127001"]["status_label"] == "待出库"

    assert client.get("/api/v1/outbound-orders?type=LOSS",
                      headers=ah).json()["data"]["total"] == 0


def test_三类Tab角标(client, ah):
    d = client.get("/api/v1/outbound-orders/status-counts", headers=ah).json()["data"]
    assert d["SALES"]["PENDING"] == 1
    assert d["PICK"]["PENDING"] == 1


def test_详情SKU编码按类型取表(so_order, client, ah):
    """销售出库单的 SKU 必须是成品编码，不能撞上同 id 的物料。"""
    d = client.get(f"/api/v1/outbound-orders/{so_order['order_id']}",
                   headers=ah).json()["data"]
    assert d["items"][0]["sku_code"] == "A3288"
    assert d["row_violations"] == [], "待出库的行不该有出库人/时间"


# ---------------------------------------------------------------- FIFO
def test_FIFO按入库时间升序推荐_BR003(so_order, stocked, client, ah):
    r = client.get(f"/api/v1/outbound-orders/{so_order['order_id']}/fifo", headers=ah)
    d = r.json()["data"]
    assert d["shortage"] == 0
    assert d["fifo"] is True
    codes = [l["location_code"] for l in d["locations"]]
    # 早入库的库位必须排在前面
    assert codes[0] == next(
        l["location_code"] for l in d["locations"]
        if l["location_id"] == stocked["early_loc"]
    ), codes


def test_FIFO库存不足时报缺口(so_order, client, ah):
    """没有任何库存时应报缺口 20。"""
    r = client.get(f"/api/v1/outbound-orders/{so_order['order_id']}/fifo", headers=ah)
    d = r.json()["data"]
    assert d["shortage"] == 20
    assert d["locations"] == []


# ---------------------------------------------------------------- 拣货
def test_扫码拣货并推进部分出库(so_order, stocked, client, kh):
    # 批量拣货不带 SN（一行一件，SN 只能一件一扫）
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
              {"location_id": stocked["early_loc"], "qty": 8})
    d = r.json()["data"]
    assert d["picked"] == 8 and d["plan_qty"] == 20
    assert d["status"] == "PARTIAL"
    assert d["remain"] == 12
    with SessionLocal() as s:
        n = s.execute(select(func.count()).select_from(OutboundItem).where(
            OutboundItem.order_id == so_order["order_id"])).scalar()
        # 种子的占位行 1 条 + 本次 8 件
        assert n == 9, n


def test_带SN必须一件一扫(so_order, stocked, client, kh):
    """outbound_item 没有 qty 列，一行一件；带 SN 就不能批量。"""
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
              {"location_id": stocked["early_loc"], "qty": 3, "sn": "SN-BULK"})
    assert r.json()["code"] == "WMS-4001"
    assert "一件一扫" in r.json()["message"]

    # 一件一扫可以
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
              {"location_id": stocked["early_loc"], "qty": 1, "sn": "SN-BULK"})
    assert r.json()["code"] == "0"


def test_可用库存不足报缺口_R5(so_order, stocked, client, kh):
    """早入库库位只有 10 件，拣 15 件应被拒并给缺口。"""
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
              {"location_id": stocked["early_loc"], "qty": 15})
    assert r.json()["code"] == "WMS-4222"
    assert r.json()["data"]["shortage"] == 5


def test_禁止超发(so_order, stocked, client, kh):
    """计划 20，拣 21 必须被拒（PRD 6.5.1）。"""
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
              {"location_id": stocked["late_loc"], "qty": 21})
    assert r.json()["code"] == "WMS-4221"
    assert "超发" in r.json()["message"]


def test_同一SN不能挂两张未关闭出库单_BR010(so_order, stocked, client, ah, kh):
    oid = so_order["order_id"]
    _post(client, f"/api/v1/outbound-orders/{oid}/pick", kh,
          {"location_id": stocked["early_loc"], "qty": 1, "sn": "SN-BR10-OUT"})

    with SessionLocal() as s:
        prod = s.execute(select(Product.id).limit(1)).scalar_one()
        o2 = OutboundOrder(no="SO20260127002", type="SALES", status="PENDING",
                           plan_qty=5, actual_qty=0, creator_id=1)
        s.add(o2)
        s.flush()
        s.add(OutboundItem(order_id=o2.id, sku_id=prod, status="PENDING"))
        s.commit()
        oid2 = o2.id

    r = _post(client, f"/api/v1/outbound-orders/{oid2}/pick", kh,
              {"location_id": stocked["early_loc"], "qty": 1, "sn": "SN-BR10-OUT"})
    assert r.json()["code"] == "WMS-4093"
    assert "BR-010" in r.json()["message"]


def test_盘点中库位不能出库_BR007(so_order, stocked, client, kh):
    """盘点会锁定库位，此时发起出库必须被拒绝（AC-07）。"""
    with SessionLocal() as s:
        s.get(Location, stocked["early_loc"]).status = "LOCKED"
        s.commit()
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
              {"location_id": stocked["early_loc"], "qty": 1})
    assert r.json()["code"] == "WMS-4221"
    assert "盘点中" in r.json()["message"]


def test_终态单不能再拣货(so_order, stocked, client, ah, kh):
    with SessionLocal() as s:
        o = s.get(OutboundOrder, so_order["order_id"])
        o.status = str(OrderStatus.DONE)
        s.commit()
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
              {"location_id": stocked["early_loc"], "qty": 1})
    assert r.json()["code"] == "WMS-4092"


# ---------------------------------------------------------------- 提交
def test_提交出库扣减库存并守恒(so_order, stocked, client, kh):
    sku = so_order["sku_id"]
    before = _stock(sku)
    assert before == 40

    # 分两批拣：8 + 12 = 20 = 计划数
    for i, qty in enumerate((8, 12)):
        r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
                  {"location_id": stocked["early_loc"] if i == 0 else stocked["late_loc"],
                   "qty": qty})
        assert r.json()["data"]["status"] == "PARTIAL"

    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/submit", kh, {})
    d = r.json()["data"]
    assert d["status"] == "DONE" and d["actual_qty"] == 20
    assert d["remain"] == 0 and d["finished_at"] is not None

    assert _stock(sku) == 20, "40 - 20 = 20"
    # 两个库位各扣一笔，所以是两条流水
    assert _txn_count("SO20260127001") == 2

    with SessionLocal() as s:
        rows = s.execute(select(OutboundItem).where(
            OutboundItem.order_id == so_order["order_id"])).scalars().all()
        # 一行一件：种子占位行 1 条 + 实拣 20 件 = 21 行；
        # 占位行没扫过码，保持 PENDING，只有实拣的 20 行转 SHIPPED
        assert len(rows) == 21, len(rows)
        assert sum(1 for i in rows if i.status == "SHIPPED") == 20
        assert sum(1 for i in rows if i.status == "PENDING") == 1


def test_没有拣货记录不能提交(so_order, stocked, client, kh):
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/submit", kh, {})
    assert r.json()["code"] == "WMS-4221"
    assert "拣货" in r.json()["message"]


def test_实收与计划不一致必须填原因_BR016(so_order, stocked, client, kh):
    _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
          {"location_id": stocked["early_loc"], "qty": 8})
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/submit", kh, {})
    assert r.json()["code"] == "WMS-4001"
    assert "差异原因" in r.json()["message"]

    assert _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/submit", kh,
                 {"reason": "短"}).json()["code"] == "WMS-4001"

    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/submit", kh,
              {"reason": "客户临时减量，余量转下周订单"})
    d = r.json()["data"]
    assert d["status"] == "PARTIAL", "短收应保持部分出库，剩余可拆单继续发"
    assert d["remain"] == 12
    assert _stock(so_order["sku_id"]) == 32, "40 - 8"


def test_提交可重复调用_每次只发新增拣货(so_order, stocked, client, kh):
    """拣一批发一批：第二次提交只扣新增的那批。"""
    sku = so_order["sku_id"]
    _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
          {"location_id": stocked["early_loc"], "qty": 8})
    _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/submit", kh,
          {"reason": "先发一部分，余量后续补"})
    assert _stock(sku) == 32

    _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
          {"location_id": stocked["late_loc"], "qty": 12})
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/submit", kh, {})
    assert r.json()["data"]["status"] == "DONE"
    assert _stock(sku) == 20, "第二次只扣新增的 12"
    assert _txn_count("SO20260127001") == 2


def test_提交是幂等的(so_order, stocked, client, kh):
    # 早入库库位只有 10 件，分两个库位拣满 20
    for loc, qty in ((stocked["early_loc"], 10), (stocked["late_loc"], 10)):
        _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
              {"location_id": loc, "qty": qty})
    op = "outbound-submit-idem-0001"
    path = f"/api/v1/outbound-orders/{so_order['order_id']}/submit"
    r1 = client.post(path, headers={**kh, "X-Client-Op-Id": op}, json={})
    r2 = client.post(path, headers={**kh, "X-Client-Op-Id": op}, json={})
    assert r1.json()["code"] == "0"
    assert r2.json()["code"] == "WMS-4091"
    assert _stock(so_order["sku_id"]) == 20, "不能扣两次"


# ---------------------------------------------------------------- 作废
def test_作废必须填原因(so_order, client, ah):
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/void", ah,
              {"reason": "  "})
    assert r.json()["code"] == "WMS-4001"


def test_作废已发货单冲销库存_BR002(so_order, stocked, client, kh, ah):
    sku = so_order["sku_id"]
    _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
          {"location_id": stocked["early_loc"], "qty": 8})
    _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/submit", kh,
          {"reason": "先发一部分，客户随后退单"})
    assert _stock(sku) == 32

    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/void", ah,
              {"reason": "客户整单取消，主管确认作废"})
    assert r.json()["data"]["status"] == "VOID"
    assert _stock(sku) == 40, "作废后库存必须冲回"
    assert _txn_count("SO20260127001") == 2, "扣减 + 冲销各一条"


def test_作废未发货单不产生流水(so_order, stocked, client, kh, ah):
    """只拣未发的单作废后不该有冲销流水。"""
    _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/pick", kh,
          {"location_id": stocked["early_loc"], "qty": 5})
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/void", ah,
              {"reason": "单据录入错误，主管确认作废"})
    assert r.json()["data"]["status"] == "VOID"
    assert _txn_count("SO20260127001") == 0, "没发过货就不该有冲销流水"
    assert _stock(so_order["sku_id"]) == 40


def test_终态不可再作废(so_order, stocked, client, ah):
    _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/void", ah,
          {"reason": "第一次作废，原因写够长度"})
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/void", ah,
              {"reason": "再作废一次"})
    assert r.json()["code"] == "WMS-4092"


# ---------------------------------------------------------------- 权限
def test_仓管员不能作废(so_order, client, kh):
    r = _post(client, f"/api/v1/outbound-orders/{so_order['order_id']}/void", kh,
              {"reason": "仓管员尝试作废"})
    assert r.status_code == 403
    assert r.json()["code"] == "WMS-4030"
