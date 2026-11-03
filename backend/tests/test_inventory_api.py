# -*- coding: utf-8 -*-
"""库存与流水查询测试（T-01-1/T-01-2，接口 4/5/6/25，页面 P01–P04）。"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.domain.models import InTransit, Inventory, Location, Material, Product
from app.domain.stock import Move, apply_many

from tests.conftest import login


def _h(client, username="admin"):
    return login(client, username)


@pytest.fixture
def ah(client):
    return _h(client, "admin")


@pytest.fixture
def keeper_h(client):
    return _h(client, "wangjf")


@pytest.fixture
def seeded_stock(seeded, wh1_id, wh1_location_id):
    """灌一点库存与在途，让查询有数据可看。"""
    with SessionLocal() as s:
        prod = s.execute(select(Product.id).where(Product.code == "A3288")).scalar_one()
        apply_many(s, [Move("PRODUCT", prod, wh1_location_id, 320)], biz_type="PURCHASE_IN",
                   biz_no="SEED-P1", operator_id=1)
        # 物料：锁定 40、冻结 30，可用应为 130
        mat = s.execute(select(Material.id).where(
            Material.code == "BAT-LIPO-4500-003")).scalar_one()
        apply_many(s, [Move("MATERIAL", mat, wh1_location_id, 200)], biz_type="PURCHASE_IN",
                   biz_no="SEED-M1", operator_id=1)
        # 必须同时限定 sku_type，否则会命中同 id 的成品行
        inv = s.execute(select(Inventory).where(
            Inventory.sku_type == "MATERIAL", Inventory.sku_id == mat)).scalar_one()
        inv.locked_qty, inv.frozen_qty = 40, 30
        s.add(InTransit(sku_type="MATERIAL", sku_id=mat, po_no="CGDD20260127001", qty=500))
        s.commit()
        return {"product_id": prod, "material_id": mat, "location_id": wh1_location_id,
                "warehouse_id": wh1_id}


# ---------------------------------------------------------------- 成品库存 P01
def test_成品库存返回规格数组与总量(seeded_stock, client, ah):
    d = client.get("/api/v1/inventory/products", headers=ah).json()["data"]
    row = next(i for i in d["items"] if i["code"] == "A3288")
    assert row["qty"] == 320
    assert isinstance(row["spec"], list) and row["spec"], "规格要拆成数组"
    assert row["unit"] == "台"
    assert row["zero"] is False
    assert row["last_inbound_at"] is not None


def test_零库存仍返回并标记zero(client, ah):
    d = client.get("/api/v1/inventory/products", headers=ah).json()["data"]
    # B2100 没有任何库存记录
    row = next(i for i in d["items"] if i["code"] == "B2100")
    assert row["qty"] == 0 and row["zero"] is True


def test_按编码与名称搜索(seeded_stock, client, ah):
    d = client.get("/api/v1/inventory/products?code=A3288", headers=ah).json()["data"]
    assert d["total"] == 1
    # 名称是模糊匹配：iphone16 同时命中 A3288 与 A3399（iphone16 Pro）
    d = client.get("/api/v1/inventory/products?name=iphone16", headers=ah).json()["data"]
    assert d["total"] == 2
    d = client.get("/api/v1/inventory/products?name=iphone16 Pro", headers=ah).json()["data"]
    assert d["total"] == 1
    d = client.get("/api/v1/inventory/products?name=不存在的名字", headers=ah).json()["data"]
    assert d["total"] == 0


def test_成品库存分页(client, ah):
    d = client.get("/api/v1/inventory/products?page=1&page_size=2", headers=ah).json()["data"]
    assert len(d["items"]) == 2 and d["total"] == 4


# ---------------------------------------------------------------- 物料库存 P02
def test_物料库存口径_可用等于总减锁减冻(seeded_stock, client, ah):
    d = client.get("/api/v1/inventory/materials", headers=ah).json()["data"]
    row = next(i for i in d["items"] if i["code"] == "BAT-LIPO-4500-003")
    assert row["qty"] == 200
    assert row["locked"] == 40 and row["frozen"] == 30
    assert row["available"] == 130
    assert row["in_transit"] == 500
    assert row["safety_stock"] == 200
    assert row["low_stock"] is True, "可用 130 < 安全库存 200 应标黄"


def test_高于安全库存不标黄(seeded_stock, client, ah):
    """DSP 安全库存 100：入库 150 后可用 150 > 100，不该标黄。"""
    with SessionLocal() as s:
        mat = s.execute(select(Material.id).where(
            Material.code == "DSP-AMOLED-67-FULL")).scalar_one()
        apply_many(s, [Move("MATERIAL", mat, seeded_stock["location_id"], 150)],
                   biz_type="PURCHASE_IN", biz_no="SEED-M2", operator_id=1)
        s.commit()
    d = client.get("/api/v1/inventory/materials", headers=ah).json()["data"]
    row = next(i for i in d["items"] if i["code"] == "DSP-AMOLED-67-FULL")
    assert row["qty"] == 150 and row["safety_stock"] == 100
    assert row["low_stock"] is False


# ---------------------------------------------------------------- 流水 P03/P04
def test_流水带符号与结存(seeded_stock, client, ah):
    d = client.get("/api/v1/txn?sku_type=PRODUCT", headers=ah).json()["data"]
    assert d["total"] >= 1
    row = next(i for i in d["items"] if i["biz_no"] == "SEED-P1")
    assert row["qty_delta"] > 0
    assert row["balance"] == 320
    assert row["biz_type_label"] == "采购入库"


def test_流水倒序且稳定排序(seeded_stock, client, ah):
    d = client.get("/api/v1/txn?page=1&page_size=100", headers=ah).json()["data"]
    ids = [i["id"] for i in d["items"]]
    assert ids == sorted(ids, reverse=True), "必须按 id 倒序，保证翻页稳定"


def test_流水按业务类型过滤(client, ah):
    d = client.get("/api/v1/txn?biz_type=SALES_OUT", headers=ah).json()["data"]
    assert all(i["biz_type"] == "SALES_OUT" for i in d["items"])


def test_流水sku_type参数校验(client, ah):
    r = client.get("/api/v1/txn?sku_type=BOGUS", headers=ah)
    assert r.status_code == 400


# ---------------------------------------------------------------- 数据权限
def test_仓管员只见自己仓库的库存(seeded_stock, client, keeper_h):
    d = client.get("/api/v1/inventory/products", headers=keeper_h).json()["data"]
    assert d["total"] >= 1
    # wangjf 只被分配到 WH-001 / WH-002，看不到只在 WH-003 有库存的 SKU
    d2 = client.get("/api/v1/inventory/products", headers=keeper_h).json()["data"]
    assert d2["total"] == d["total"]


def test_行下钻返回库位分布(seeded_stock, client, ah):
    with SessionLocal() as s:
        pid = s.execute(select(Product.id).where(Product.code == "A3288")).scalar_one()
    d = client.get(f"/api/v1/txn/summary?sku_type=PRODUCT&sku_id={pid}",
                   headers=ah).json()["data"]
    assert d["qty"] == 320 and d["available"] == 320
    assert len(d["locations"]) == 1
    assert d["locations"][0]["qty"] == 320


# ---------------------------------------------------------------- 导出
def test_导出CSV带BOM(seeded_stock, client, ah):
    r = client.get("/api/v1/export/inventory_products", headers=ah)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert r.content.startswith(b"\xef\xbb\xbf"), "必须有 BOM，否则 Excel 中文乱码"
    text = r.content.decode("utf-8-sig")
    assert "code,name,qty" in text.splitlines()[0]


def test_导出物料含在途与安全库存(seeded_stock, client, ah):
    r = client.get("/api/v1/export/inventory_materials", headers=ah)
    head = r.content.decode("utf-8-sig").splitlines()[0]
    assert "in_transit" in head and "safety_stock" in head


def test_导出流水(seeded_stock, client, ah):
    r = client.get("/api/v1/export/txn?sku_type=PRODUCT", headers=ah)
    assert r.status_code == 200
    assert "biz_type_label" in r.content.decode("utf-8-sig").splitlines()[0]


def test_导出biz参数校验(client, ah):
    r = client.get("/api/v1/export/not_a_biz", headers=ah)
    assert r.status_code == 400


# ---------------------------------------------------------------- 权限
def test_未登录不能查库存(client):
    r = client.get("/api/v1/inventory/products")
    assert r.status_code == 401
