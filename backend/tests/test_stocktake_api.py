# -*- coding: utf-8 -*-
"""盘点闭环测试（T-03-1/2/3，接口 13–15、30–32，页面 P15/P16）。

覆盖：创建即锁库位（BR-007）、盲盘隐藏账面（BR-024）、未盘不允许提交、
盈亏生成 SG/SL 单据 + 库存调整流水、提交后解锁、盘盈按 book_qty=0 建行。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.domain.models import (
    InboundOrder,
    Inventory,
    Location,
    Material,
    OutboundOrder,
    StocktakeItem,
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
def sh(client):
    return login(client, "supervisor")


@pytest.fixture
def kh(client):
    return login(client, "wangjf")


@pytest.fixture
def stocked(seeded, wh1_id, wh1_location_id):
    """在 WH-001 的两个库位放物料，让盘点有账面数。"""
    with SessionLocal() as s:
        mat = s.execute(select(Material.id).where(
            Material.code == "BAT-LIPO-4500-003")).scalar_one()
        locs = s.execute(
            select(Location.id).where(Location.warehouse_id == wh1_id)
            .order_by(Location.id).limit(2)
        ).scalars().all()
        apply_many(s, [Move("MATERIAL", mat, locs[0], 100)], biz_type="PURCHASE_IN",
                   biz_no="PD-SEED-1", operator_id=1)
        apply_many(s, [Move("MATERIAL", mat, locs[1], 50)], biz_type="PURCHASE_IN",
                   biz_no="PD-SEED-2", operator_id=1)
        s.commit()
    return {"material_id": mat, "loc_a": locs[0], "loc_b": locs[1], "warehouse_id": wh1_id}


def _qty(material_id: int, location_id: int) -> int:
    with SessionLocal() as s:
        return int(s.execute(
            select(func.coalesce(func.sum(Inventory.qty), 0)).where(
                Inventory.sku_type == "MATERIAL", Inventory.sku_id == material_id,
                Inventory.location_id == location_id)
        ).scalar())


def _create(client, sh, wh_id, **kw):
    return _post(client, "/api/v1/stocktakes", sh,
                 {"warehouse_id": wh_id, "type": "FULL", **kw})


# ---------------------------------------------------------------- 创建
def test_创建盘点单锁定库位_BR007(stocked, client, sh):
    r = _create(client, sh, stocked["warehouse_id"])
    d = r.json()["data"]
    assert r.json()["code"] == "0"
    assert d["no"].startswith("PD")
    assert d["total"] == 2, "两个库位各有一条账面库存"
    assert d["mode"] == "BLIND", "默认盲盘（BR-024）"

    with SessionLocal() as s:
        locked = s.execute(
            select(func.count()).select_from(Location).where(
                Location.warehouse_id == stocked["warehouse_id"],
                Location.status == "LOCKED")
        ).scalar()
    assert locked > 0, "创建即锁定库位"


def test_明盘可显式指定(stocked, client, sh):
    d = _create(client, sh, stocked["warehouse_id"], mode="OPEN").json()["data"]
    assert d["mode"] == "OPEN" and d["mode_label"] == "明盘"


def test_仓管员不能创建盘点单(client, kh, wh1_id):
    r = _post(client, "/api/v1/stocktakes", kh, {"warehouse_id": wh1_id})
    assert r.status_code == 403
    assert r.json()["code"] == "WMS-4030"


def test_无库位可盘时报错(client, sh, wh3_id):
    """WH-003 的库位状态都不是空闲/占用时应当报错。"""
    with SessionLocal() as s:
        for loc in s.execute(select(Location).where(
                Location.warehouse_id == wh3_id)).scalars():
            loc.status = "MAINTAIN"
        s.commit()
    r = _create(client, sh, wh3_id)
    assert r.json()["code"] == "WMS-4221"


# ---------------------------------------------------------------- 盲盘
def test_盲盘对仓管员隐藏账面(stocked, client, sh, kh):
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]

    # 主管看得到账面
    items = client.get(f"/api/v1/stocktakes/{sid}/items", headers=sh).json()["data"]
    assert all("book_qty" in i for i in items)

    # 仓管员看不到（字段根本不返回，不是置空）
    items_k = client.get(f"/api/v1/stocktakes/{sid}/items", headers=kh).json()["data"]
    assert all("book_qty" not in i and "diff" not in i for i in items_k)


def test_明盘对仓管员可见账面(stocked, client, sh, kh):
    sid = _create(client, sh, stocked["warehouse_id"], mode="OPEN").json()["data"]["id"]
    items = client.get(f"/api/v1/stocktakes/{sid}/items", headers=kh).json()["data"]
    assert all("book_qty" in i for i in items)


def test_盲盘实盘响应也不揭晓差异(stocked, client, sh, kh):
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    r = _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
              {"location_id": stocked["loc_a"], "material_id": stocked["material_id"],
               "real_qty": 90})
    d = r.json()["data"]
    assert "book_qty" not in d and "diff" not in d
    assert d["status"] == "COUNTING"


# ---------------------------------------------------------------- 实盘
def test_盘完进入待确认(stocked, client, sh, kh):
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    for loc in (stocked["loc_a"], stocked["loc_b"]):
        r = _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
                  {"location_id": loc, "material_id": stocked["material_id"],
                   "real_qty": 10})
    d = r.json()["data"]
    assert d["done"] == 2 and d["total"] == 2
    assert d["status"] == "CONFIRMING", "全部盘完应转待确认"


def test_实盘为0与未盘是两回事(stocked, client, sh, kh):
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    r = _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
              {"location_id": stocked["loc_a"], "material_id": stocked["material_id"],
               "real_qty": 0})
    assert r.json()["data"]["done"] == 1, "实盘 0 也算已盘"
    items = client.get(f"/api/v1/stocktakes/{sid}/items", headers=sh).json()["data"]
    counted = [i for i in items if i["counted"]]
    assert len(counted) == 1 and counted[0]["real_qty"] == 0


def test_盘出账面没有的物料按盘盈建行(stocked, client, sh, kh):
    """扫到账面没有的 (库位, 物料) 时，book_qty=0，提交后算盘盈。"""
    with SessionLocal() as s:
        other = s.execute(select(Material.id).where(
            Material.code == "PCB-MAIN-V3")).scalar_one()
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    before = client.get(f"/api/v1/stocktakes/{sid}", headers=sh).json()["data"]["total"]

    r = _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
              {"location_id": stocked["loc_a"], "material_id": other, "real_qty": 7})
    assert r.json()["code"] == "0"
    after = client.get(f"/api/v1/stocktakes/{sid}", headers=sh).json()["data"]["total"]
    assert after == before + 1, "新增一行，应盘总数要跟着加"

    items = client.get(f"/api/v1/stocktakes/{sid}/items", headers=sh).json()["data"]
    row = next(i for i in items if i["material_id"] == other)
    assert row["book_qty"] == 0 and row["diff"] == 7


def test_未盘不允许提交(stocked, client, sh, kh):
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
          {"location_id": stocked["loc_a"], "material_id": stocked["material_id"],
           "real_qty": 10})
    r = _post(client, f"/api/v1/stocktakes/{sid}/submit", sh, {})
    assert r.json()["code"] == "WMS-4221"
    assert r.json()["data"]["undone"] == 1


def test_库位不属于本仓被拒(stocked, client, sh, kh, wh3_id):
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    with SessionLocal() as s:
        other_loc = s.execute(select(Location.id).where(
            Location.warehouse_id == wh3_id).limit(1)).scalar_one()
    r = _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
              {"location_id": other_loc, "material_id": stocked["material_id"],
               "real_qty": 1})
    assert r.json()["code"] == "WMS-4001"


# ---------------------------------------------------------------- 提交与盈亏
def test_盘亏生成待执行SL单且库存暂不变(stocked, client, sh, kh):
    """两步走：盘点提交只出单，库存要等仓管员执行盘亏出库单才动（PRD 6.5.3）。"""
    mat, loc = stocked["material_id"], stocked["loc_a"]
    assert _qty(mat, loc) == 100
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]

    _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
          {"location_id": loc, "material_id": mat, "real_qty": 92})
    _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
          {"location_id": stocked["loc_b"], "material_id": mat, "real_qty": 50})

    r = _post(client, f"/api/v1/stocktakes/{sid}/submit", sh, {})
    d = r.json()["data"]
    assert r.json()["code"] == "0", r.text
    assert d["status"] == "DONE"
    assert d["diff_loss"] == 1 and d["diff_gain"] == 0
    assert d["loss_no"].startswith("SL")
    assert d["docs_pending"] is True

    # 关键：单据已生成，但库存还没动
    assert _qty(mat, loc) == 100, "盘点提交本身不扣库存"

    with SessionLocal() as s:
        o = s.execute(select(OutboundOrder).where(
            OutboundOrder.no == d["loss_no"])).scalar_one()
        assert o.type == "LOSS" and o.status == "PENDING"
        assert o.source_no.startswith("PD")
        n = s.execute(select(func.count()).select_from(Txn).where(
            Txn.biz_no == d["loss_no"])).scalar()
        assert n == 0, "还没执行，不该有流水"

    # 仓管员执行盘亏出库单 → 这时才扣库存
    r = _post(client, f"/api/v1/outbound-orders/{o.id}/submit", kh, {})
    assert r.json()["code"] == "0", r.text
    assert r.json()["data"]["status"] == "DONE"
    assert _qty(mat, loc) == 92, "执行后盘亏 8 件扣掉"
    assert _qty(mat, stocked["loc_b"]) == 50, "无差异的库位不动"

    with SessionLocal() as s:
        n = s.execute(select(func.count()).select_from(Txn).where(
            Txn.biz_no == d["loss_no"])).scalar()
        assert n == 1, "库存调整流水在单据执行时写入"


def test_盘盈生成待执行SG单_执行后才加库存(stocked, client, sh, kh):
    mat, loc = stocked["material_id"], stocked["loc_a"]
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
          {"location_id": loc, "material_id": mat, "real_qty": 108})
    _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
          {"location_id": stocked["loc_b"], "material_id": mat, "real_qty": 50})

    d = _post(client, f"/api/v1/stocktakes/{sid}/submit", sh, {}).json()["data"]
    assert d["diff_gain"] == 1 and d["diff_loss"] == 0
    assert d["gain_no"].startswith("SG")
    assert _qty(mat, loc) == 100, "盘点提交本身不加库存"

    with SessionLocal() as s:
        o = s.execute(select(InboundOrder).where(
            InboundOrder.no == d["gain_no"])).scalar_one()
        assert o.type == "GAIN" and o.status == "PENDING"

    # 仓管员执行盘盈入库单
    r = _post(client, f"/api/v1/inbound-orders/{o.id}/submit", kh, {})
    assert r.json()["code"] == "0", r.text
    assert _qty(mat, loc) == 108


def test_提交后解锁库位(stocked, client, sh, kh):
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    for loc in (stocked["loc_a"], stocked["loc_b"]):
        _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
              {"location_id": loc, "material_id": stocked["material_id"], "real_qty": 10})
    _post(client, f"/api/v1/stocktakes/{sid}/submit", sh, {})

    with SessionLocal() as s:
        locked = s.execute(select(func.count()).select_from(Location).where(
            Location.warehouse_id == stocked["warehouse_id"],
            Location.status == "LOCKED")).scalar()
        assert locked == 0, "提交后必须解锁"
        # 有库存的库位应回到「占用」
        loc = s.get(Location, stocked["loc_a"])
        assert loc.status == "OCCUPIED"  # 库位里仍有 100 件


def test_无差异不生成单据(stocked, client, sh, kh):
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
          {"location_id": stocked["loc_a"], "material_id": stocked["material_id"],
           "real_qty": 100})
    _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
          {"location_id": stocked["loc_b"], "material_id": stocked["material_id"],
           "real_qty": 50})
    d = _post(client, f"/api/v1/stocktakes/{sid}/submit", sh, {}).json()["data"]
    assert d["diff_loss"] == 0 and d["diff_gain"] == 0
    assert d["loss_no"] is None and d["gain_no"] is None
    assert _qty(stocked["material_id"], stocked["loc_a"]) == 100


def test_终态不可重复提交(stocked, client, sh, kh):
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    for loc in (stocked["loc_a"], stocked["loc_b"]):
        _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
              {"location_id": loc, "material_id": stocked["material_id"], "real_qty": 10})
    _post(client, f"/api/v1/stocktakes/{sid}/submit", sh, {})
    r = _post(client, f"/api/v1/stocktakes/{sid}/submit", sh, {})
    assert r.json()["code"] == "WMS-4092"


def test_仓管员不能提交盘点(stocked, client, sh, kh):
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    for loc in (stocked["loc_a"], stocked["loc_b"]):
        _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
              {"location_id": loc, "material_id": stocked["material_id"], "real_qty": 10})
    r = _post(client, f"/api/v1/stocktakes/{sid}/submit", kh, {})
    assert r.status_code == 403


# ---------------------------------------------------------------- 列表
def test_列表带已盘未盘与盈亏数(stocked, client, sh, kh):
    sid = _create(client, sh, stocked["warehouse_id"]).json()["data"]["id"]
    _post(client, f"/api/v1/stocktakes/{sid}/count", kh,
          {"location_id": stocked["loc_a"], "material_id": stocked["material_id"],
           "real_qty": 90})
    d = client.get("/api/v1/stocktakes", headers=sh).json()["data"]
    row = next(i for i in d["items"] if i["id"] == sid)
    assert row["total"] == 2 and row["done"] == 1 and row["undone"] == 1
    assert row["mode_label"] == "盲盘"


def test_列表筛选(client, sh):
    assert client.get("/api/v1/stocktakes?type=SPOT", headers=sh).json()["data"]["total"] == 0
    assert client.get("/api/v1/stocktakes?status=DONE", headers=sh).json()["data"]["total"] == 0
