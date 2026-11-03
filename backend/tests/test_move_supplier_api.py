# -*- coding: utf-8 -*-
"""移位与供应商测试（T-03-4 / T-03-5，接口 16/17/33、21/47）。"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.domain.models import Inventory, Location, Material, MoveOrder, Supplier, Txn
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
def sh(client):
    return login(client, "supervisor")


@pytest.fixture
def two_locs(seeded, wh1_id):
    """同一仓库的两个空闲库位 + 一个物料，源库位放 50。"""
    with SessionLocal() as s:
        mat = s.execute(select(Material.id).where(
            Material.code == "BAT-LIPO-4500-003")).scalar_one()
        locs = s.execute(
            select(Location).where(Location.warehouse_id == wh1_id,
                                   Location.status == "IDLE").order_by(Location.id).limit(2)
        ).scalars().all()
        apply_many(s, [Move("MATERIAL", mat, locs[0].id, 50)], biz_type="PURCHASE_IN",
                   biz_no="MV-SEED", operator_id=1)
        s.commit()
        return {"material_id": mat, "src": locs[0].id, "dst": locs[1].id,
                "dst_code": locs[1].code, "src_code": locs[0].code}


def _qty(material_id: int, location_id: int) -> int:
    with SessionLocal() as s:
        return int(s.execute(
            select(func.coalesce(func.sum(Inventory.qty), 0)).where(
                Inventory.sku_type == "MATERIAL", Inventory.sku_id == material_id,
                Inventory.location_id == location_id)
        ).scalar())


# ---------------------------------------------------------------- 移位
def test_移位改写库位维度且总量不变(two_locs, client, kh):
    m, src, dst = two_locs["material_id"], two_locs["src"], two_locs["dst"]
    before_total = _qty(m, src) + _qty(m, dst)
    assert before_total == 50

    r = _post(client, "/api/v1/move-orders", kh,
              {"material_id": m, "from_location_id": src, "to_location_id": dst, "qty": 20})
    d = r.json()["data"]
    assert r.json()["code"] == "0", r.text
    assert d["no"].startswith("YK")
    assert d["status"] == "DONE"
    assert _qty(m, src) == 30 and _qty(m, dst) == 20
    assert _qty(m, src) + _qty(m, dst) == before_total, "移位不改总量"


def test_移位写一条业务流水(two_locs, client, kh):
    m = two_locs["material_id"]
    _post(client, "/api/v1/move-orders", kh,
          {"material_id": m, "from_location_id": two_locs["src"],
           "to_location_id": two_locs["dst"], "qty": 5})
    with SessionLocal() as s:
        o = s.execute(select(MoveOrder)).scalars().first()
        rows = s.execute(select(Txn).where(Txn.biz_no == o.no)).scalars().all()
    # 流水按库位拆行：移出 +1、移入 -1，同为一张移位单的业务号
    assert len(rows) == 2
    assert sum(r.qty_delta for r in rows) == 0, "移位不改总量"
    assert {r.location_id for r in rows} == {two_locs["src"], two_locs["dst"]}


def test_源库位清空后转空闲(two_locs, client, kh):
    m = two_locs["material_id"]
    _post(client, "/api/v1/move-orders", kh,
          {"material_id": m, "from_location_id": two_locs["src"],
           "to_location_id": two_locs["dst"], "qty": 50})
    with SessionLocal() as s:
        loc = s.get(Location, two_locs["src"])
    assert loc.status == "IDLE", "移空后状态自动回到空闲"


def test_目标库位转占用(two_locs, client, kh):
    _post(client, "/api/v1/move-orders", kh,
          {"material_id": two_locs["material_id"], "from_location_id": two_locs["src"],
           "to_location_id": two_locs["dst"], "qty": 10})
    with SessionLocal() as s:
        assert s.get(Location, two_locs["dst"]).status == "OCCUPIED"


def test_可用库存不足被拒(two_locs, client, kh):
    r = _post(client, "/api/v1/move-orders", kh,
              {"material_id": two_locs["material_id"],
               "from_location_id": two_locs["src"],
               "to_location_id": two_locs["dst"], "qty": 999})
    assert r.json()["code"] == "WMS-4222"
    assert r.json()["data"]["available"] == 50


def test_同库位移位被拒(two_locs, client, kh):
    r = _post(client, "/api/v1/move-orders", kh,
              {"material_id": two_locs["material_id"],
               "from_location_id": two_locs["src"],
               "to_location_id": two_locs["src"], "qty": 1})
    assert r.json()["code"] == "WMS-4001"


def test_目标容量不足被拒(two_locs, client, kh):
    with SessionLocal() as s:
        loc = s.get(Location, two_locs["dst"])
        loc.cap_material = 15
        s.commit()
    r = _post(client, "/api/v1/move-orders", kh,
              {"material_id": two_locs["material_id"],
               "from_location_id": two_locs["src"],
               "to_location_id": two_locs["dst"], "qty": 20})
    assert r.json()["code"] == "WMS-4221"
    assert r.json()["data"]["remain_capacity"] == 15


def test_锁定库位不能作为目标(two_locs, client, kh):
    with SessionLocal() as s:
        s.get(Location, two_locs["dst"]).status = "LOCKED"
        s.commit()
    r = _post(client, "/api/v1/move-orders", kh,
              {"material_id": two_locs["material_id"],
               "from_location_id": two_locs["src"],
               "to_location_id": two_locs["dst"], "qty": 1})
    assert r.json()["code"] == "WMS-4221"
    assert "锁定" in r.json()["message"]


def test_跨仓库移位被拒(two_locs, client, kh, wh3_id):
    with SessionLocal() as s:
        other = s.execute(select(Location.id).where(
            Location.warehouse_id == wh3_id).limit(1)).scalar_one()
    r = _post(client, "/api/v1/move-orders", kh,
              {"material_id": two_locs["material_id"],
               "from_location_id": two_locs["src"],
               "to_location_id": other, "qty": 1})
    assert r.json()["code"] == "WMS-4221"
    assert "跨仓库" in r.json()["message"]


def test_危品库位只能放危品(two_locs, client, kh, wh1_id):
    """普通物料不能移进危品库位（BR-013）。危品库位要在同一仓库，
    否则会先被「跨仓库」拦掉。"""
    with SessionLocal() as s:
        danger = Location(code="DNG-MV-01", name="危品测试库位", type="DANGEROUS",
                          warehouse_id=wh1_id, cap_pallet=8, cap_material=100,
                          status="IDLE")
        s.add(danger)
        s.commit()
        danger_id = danger.id
    r = _post(client, "/api/v1/move-orders", kh,
              {"material_id": two_locs["material_id"],
               "from_location_id": two_locs["src"],
               "to_location_id": danger_id, "qty": 1})
    assert r.json()["code"] == "WMS-4221"
    assert "危品" in r.json()["message"]


def test_移位单列表与详情(two_locs, client, kh):
    d = _post(client, "/api/v1/move-orders", kh,
              {"material_id": two_locs["material_id"],
               "from_location_id": two_locs["src"],
               "to_location_id": two_locs["dst"], "qty": 3}).json()["data"]

    lst = client.get("/api/v1/move-orders", headers=kh).json()["data"]
    assert lst["total"] == 1
    row = lst["items"][0]
    assert row["no"] == d["no"]
    assert row["from_location_code"] == two_locs["src_code"]
    assert row["to_location_code"] == two_locs["dst_code"]
    assert row["material_code"] == "BAT-LIPO-4500-003"

    detail = client.get(f"/api/v1/move-orders/{d['id']}", headers=kh).json()["data"]
    assert detail["qty"] == 3 and detail["status_label"] == "已完成"


# ---------------------------------------------------------------- 供应商
def test_供应商列表(client, ah):
    d = client.get("/api/v1/suppliers", headers=ah).json()["data"]
    assert len(d) == 3
    byd = next(s for s in d if s["code"] == "GYS-BYD-002")
    assert byd["over_receive"] == 0.08, "种子里的覆盖值"
    zte = next(s for s in d if s["code"] == "GYS-ZTE-001")
    assert zte["over_receive"] is None, "未覆盖时为 null"


def test_修改超收覆盖值_BR023(client, ah):
    d = client.get("/api/v1/suppliers", headers=ah).json()["data"]
    zte = next(s for s in d if s["code"] == "GYS-ZTE-001")
    r = client.put(f"/api/v1/suppliers/{zte['id']}",
                   headers={**ah, "X-Client-Op-Id": str(uuid.uuid4())},
                   json={"over_receive": 0.12})
    assert r.json()["data"]["over_receive"] == 0.12

    # 传 null 表示清除覆盖，回落全局默认
    r = client.put(f"/api/v1/suppliers/{zte['id']}",
                   headers={**ah, "X-Client-Op-Id": str(uuid.uuid4())},
                   json={"over_receive": None})
    assert r.json()["data"]["over_receive"] is None


def test_改供应商名称与联系人(client, ah):
    d = client.get("/api/v1/suppliers", headers=ah).json()["data"]
    zte = next(s for s in d if s["code"] == "GYS-ZTE-001")
    client.put(f"/api/v1/suppliers/{zte['id']}",
               headers={**ah, "X-Client-Op-Id": str(uuid.uuid4())},
               json={"name": "中兴通讯（改名）", "contact": "021-00000000"})
    d2 = client.get("/api/v1/suppliers?code=GYS-ZTE-001", headers=ah).json()["data"]
    assert d2[0]["name"] == "中兴通讯（改名）"
    assert d2[0]["contact"] == "021-00000000"


def test_超收覆盖值影响检验判定_BR023(client, ah, ih, pending_inspection):
    """把 ZTE 的阈值改到 20%，计划 500 时 590 件就应当放行（默认 5% 会拒）。"""
    d = client.get("/api/v1/suppliers", headers=ah).json()["data"]
    zte = next(s for s in d if s["code"] == "GYS-ZTE-001")
    client.put(f"/api/v1/suppliers/{zte['id']}",
               headers={**ah, "X-Client-Op-Id": str(uuid.uuid4())},
               json={"over_receive": 0.20})

    iid, mat = pending_inspection["inspection_id"], pending_inspection["material_id"]
    _post(client, f"/api/v1/inspections/{iid}/scan", ih,
          {"material_id": mat, "actual_qty": 590})
    r = _post(client, f"/api/v1/inspections/{iid}/judge", ih, {"result": "OVER_PASS"})
    assert r.json()["code"] == "0", "阈值被覆盖到 20% 后应放行"


@pytest.fixture
def ih(client):
    return login(client, "liq")


@pytest.fixture
def pending_inspection(seeded):
    from app.domain.models import Inspection

    with SessionLocal() as s:
        iid = s.execute(select(Inspection.id).where(
            Inspection.no == "JY20260127001")).scalar_one()
        mat = s.execute(select(Material.id).where(
            Material.code == "BAT-LIPO-4500-003")).scalar_one()
    return {"inspection_id": iid, "material_id": mat}


def test_供应商不存在(client, ah):
    r = client.put("/api/v1/suppliers/999999",
                   headers={**ah, "X-Client-Op-Id": str(uuid.uuid4())},
                   json={"name": "x"})
    assert r.json()["code"] == "WMS-4001"


def test_仓管员不能改供应商(client, kh):
    d = client.get("/api/v1/suppliers", headers=client and login(client, "admin")).json()["data"]
    r = client.put(f"/api/v1/suppliers/{d[0]['id']}",
                   headers={**kh, "X-Client-Op-Id": str(uuid.uuid4())},
                   json={"over_receive": 0.3})
    assert r.status_code == 403
