# -*- coding: utf-8 -*-
"""基础资料接口测试（T-00-10 交付物，接口 18–20、39–46；BR-009 / BR-013 / BR-014 / BR-025）。"""
from __future__ import annotations

import pytest
import uuid

from app.core.db import SessionLocal
from app.core.redis import rds
from app.domain.models import InboundOrder
from app.domain.stock import Move, apply_many

from tests.conftest import login


def op_id() -> str:
    """每次写请求都要新的 client_op_id，否则会被幂等中间件判为重放。"""
    return str(uuid.uuid4())


WAREHOUSE = {"code": "WH-009", "name": "9#测试仓", "type": "AUX"}
def location_body(warehouse_id: int, **over) -> dict:
    """库位表单体。warehouse_id 必须由夹具给出，不能写死。"""
    return {"code": "Z9-01-01", "name": "测试库位", "type": "NORMAL",
            "warehouse_id": warehouse_id, "cap_pallet": 8, "cap_material": 100,
            "coord_x": 3, "coord_y": 4, **over}


def _headers_for(client, username: str) -> dict:
    cap = client.get("/api/v1/auth/captcha").json()["data"]
    r = client.post("/api/v1/auth/login",
                    json={"username": username, "password": username,
                          "captcha_id": cap["captcha_id"],
                          "captcha": rds.get(f"captcha:{cap['captcha_id']}")})
    assert r.json()["code"] == "0", r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture
def ah(client):
    """管理员 header。"""
    return _headers_for(client, "admin")


@pytest.fixture
def keeper_h(client):
    return _headers_for(client, "wangjf")


@pytest.fixture
def new_location(client, ah, wh1_id) -> int:
    r = client.post("/api/v1/locations", headers={**ah, "X-Client-Op-Id": op_id()},
                    json=location_body(wh1_id))
    assert r.json()["code"] == "0", r.text
    return r.json()["data"]["id"]


# ---------------------------------------------------------------- 仓库
def test_仓库列表带库位数量(client, ah):
    items = client.get("/api/v1/warehouses", headers=ah).json()["data"]
    assert len(items) == 3
    wh1 = next(i for i in items if i["code"] == "WH-001")
    assert wh1["location_count"] == 12


def test_新增仓库(client, ah):
    r = client.post("/api/v1/warehouses", headers={**ah, "X-Client-Op-Id": op_id()}, json=WAREHOUSE)
    assert r.json()["code"] == "0"
    wid = r.json()["data"]["id"]
    items = client.get("/api/v1/warehouses", headers=ah).json()["data"]
    assert next(i for i in items if i["id"] == wid)["name"] == "9#测试仓"


def test_仓库编码重复被拒(client, ah):
    assert client.post("/api/v1/warehouses", headers={**ah, "X-Client-Op-Id": op_id()},
                       json=WAREHOUSE).json()["code"] == "0"
    r = client.post("/api/v1/warehouses",
                    headers={**ah, "X-Client-Op-Id": op_id()},
                    json=WAREHOUSE)
    assert r.json()["code"] == "WMS-4093"


def test_编辑仓库(client, ah):
    wid = client.post("/api/v1/warehouses", headers={**ah, "X-Client-Op-Id": op_id()},
                      json=WAREHOUSE).json()["data"]["id"]
    r = client.put(f"/api/v1/warehouses/{wid}",
                   headers={**ah, "X-Client-Op-Id": op_id()},
                   json={**WAREHOUSE, "name": "9#测试仓改名"})
    assert r.json()["code"] == "0"
    items = client.get("/api/v1/warehouses", headers=ah).json()["data"]
    assert next(i for i in items if i["id"] == wid)["name"] == "9#测试仓改名"


def test_停用仓库_BR014_无阻塞可停(client, ah, wh1_id):
    r = client.post(f"/api/v1/warehouses/{wh1_id}/toggle",
                    headers={**ah, "X-Client-Op-Id": op_id()}, json={"status": "DISABLED"})
    assert r.json()["code"] == "0"
    items = client.get("/api/v1/warehouses", headers=ah).json()["data"]
    assert next(i for i in items if i["id"] == wh1_id)["status"] == "DISABLED"


def test_停用仓库_BR014_有未结单据被拒并列出阻塞项(client, ah, wh1_id, admin_id):
    with SessionLocal() as s:
        s.add(InboundOrder(no="PR20260130001", type="PURCHASE", status="PENDING",
                           plan_qty=100, creator_id=admin_id))
        s.commit()
    r = client.post(f"/api/v1/warehouses/{wh1_id}/toggle",
                    headers={**ah, "X-Client-Op-Id": op_id()}, json={"status": "DISABLED"})
    assert r.json()["code"] == "WMS-4221"
    blockers = r.json()["data"]["blockers"]
    assert any("未结入库单" in b for b in blockers), blockers
    # 列表接口也要能给出同样的阻塞项
    r2 = client.get(f"/api/v1/warehouses/{wh1_id}/blockers", headers=ah)
    assert r2.json()["data"]["blockers"] == blockers


def test_停用仓库_BR014_有库存被拒(client, ah, wh1_id, wh1_location_id):
    with SessionLocal() as s:
        apply_many(s, [Move("PRODUCT", 1, wh1_location_id, 12)], biz_type="PURCHASE_IN",
                   biz_no="T-WH-BLOCK", operator_id=1)
        s.commit()
    r = client.post(f"/api/v1/warehouses/{wh1_id}/toggle",
                    headers={**ah, "X-Client-Op-Id": op_id()}, json={"status": "DISABLED"})
    assert r.json()["code"] == "WMS-4221"
    assert any("库存 12" in b for b in r.json()["data"]["blockers"])


# ---------------------------------------------------------------- 库位
def test_库位列表标记坐标缺失_BR025(client, ah, new_location, wh1_id):
    items = client.get("/api/v1/locations", headers=ah).json()["data"]["items"]
    loc = next(i for i in items if i["code"] == "Z9-01-01")
    assert loc["coord_missing"] is False
    assert loc["warehouse_name"] == "1#原料仓"

    r = client.post("/api/v1/locations",
                    headers={**ah, "X-Client-Op-Id": op_id()},
                    json=location_body(wh1_id, code="Z9-01-09", coord_x=None, coord_y=None))
    assert r.json()["code"] == "0"
    items = client.get("/api/v1/locations", headers=ah).json()["data"]["items"]
    assert next(i for i in items if i["code"] == "Z9-01-09")["coord_missing"] is True


def test_库位分页(client, ah):
    d = client.get("/api/v1/locations?page=1&page_size=5", headers=ah).json()["data"]
    assert d["page"] == 1 and d["page_size"] == 5
    assert len(d["items"]) == 5
    assert d["total"] >= 12


def test_库位编码重复被拒(client, ah, wh1_id):
    assert client.post("/api/v1/locations", headers={**ah, "X-Client-Op-Id": op_id()},
                       json=location_body(wh1_id)).json()["code"] == "0"
    r = client.post("/api/v1/locations",
                    headers={**ah, "X-Client-Op-Id": op_id()},
                    json=location_body(wh1_id))
    assert r.json()["code"] == "WMS-4093"


def test_库位归属不存在仓库被拒(client, ah):
    r = client.post("/api/v1/locations", headers={**ah, "X-Client-Op-Id": op_id()},
                    json=location_body(9999, code="Z9-01-02"))
    assert r.json()["code"] == "WMS-4001"
    assert "仓库" in r.json()["message"]


def test_人工只能设锁定或维保_BR008(client, ah, new_location):
    for status in ("IDLE", "OCCUPIED"):
        r = client.post(f"/api/v1/locations/{new_location}/status",
                        headers={**ah, "X-Client-Op-Id": op_id()}, json={"status": status})
        assert r.json()["code"] == "WMS-4221", status
    for status in ("LOCKED", "MAINTAIN"):
        r = client.post(f"/api/v1/locations/{new_location}/status",
                        headers={**ah, "X-Client-Op-Id": op_id()}, json={"status": status})
        assert r.json()["code"] == "0", status


def test_有库存的库位不能锁定(client, ah, new_location):
    with SessionLocal() as s:
        apply_many(s, [Move("PRODUCT", 1, new_location, 5)], biz_type="PURCHASE_IN",
                   biz_no="T-LOCK", operator_id=1)
        s.commit()
    r = client.post(f"/api/v1/locations/{new_location}/status",
                    headers={**ah, "X-Client-Op-Id": op_id()}, json={"status": "LOCKED"})
    assert r.json()["code"] == "WMS-4221"
    assert "库存" in r.json()["message"]


# ---------------------------------------------------------------- 条码
def test_条码全局唯一_BR009(client, ah):
    body = {"code": "KQ-100", "type": "LOCATION", "ref_id": 1}
    assert client.post("/api/v1/barcodes", headers={**ah, "X-Client-Op-Id": op_id()},
                       json=body).json()["code"] == "0"
    r = client.post("/api/v1/barcodes",
                    headers={**ah, "X-Client-Op-Id": op_id()},
                    json=body)
    assert r.json()["code"] == "WMS-4093"


def test_条码批量打印(client, ah):
    bid = client.post("/api/v1/barcodes", headers={**ah, "X-Client-Op-Id": op_id()},
                      json={"code": "KQ-101", "type": "BOX"}).json()["data"]["id"]
    d = client.post("/api/v1/barcodes/print", headers={**ah, "X-Client-Op-Id": op_id()},
                    json={"ids": [bid], "spec": "60x40", "copies": 3}).json()["data"]
    assert d["total"] == 3 and d["spec"] == "60x40"
    assert d["items"][0]["code"] == "KQ-101"


def test_条码打印规格校验(client, ah):
    r = client.post("/api/v1/barcodes/print", headers={**ah, "X-Client-Op-Id": op_id()},
                    json={"ids": [1], "spec": "99x99", "copies": 1})
    assert r.status_code == 400


# ---------------------------------------------------------------- 权限
def test_仓管员只能读不能写(client, keeper_h):
    assert client.get("/api/v1/warehouses", headers=keeper_h).json()["code"] == "0"
    r = client.post("/api/v1/warehouses", headers={**keeper_h, "X-Client-Op-Id": op_id()},
                    json=WAREHOUSE)
    assert r.status_code == 403
    assert r.json()["code"] == "WMS-4030"


def test_写操作必须带client_op_id(client, ah):
    r = client.post("/api/v1/warehouses", headers=ah, json=WAREHOUSE)
    assert r.status_code == 400
    assert "client_op_id" in r.json()["message"]


# ---------------------------------------------------------------- 数据权限（接口 1.4）
def test_仓管员只看得见被分配的仓库(client, keeper_h):
    """wangjf 只被分配到 WH-001 / WH-002。"""
    items = client.get("/api/v1/warehouses", headers=keeper_h).json()["data"]
    assert {i["code"] for i in items} == {"WH-001", "WH-002"}


def test_主管看得见全部仓库(client):
    h = login(client, "supervisor")
    items = client.get("/api/v1/warehouses", headers=h).json()["data"]
    assert len(items) == 3


def test_仓管员显式传未分配仓库被拒_WMS4030(client, keeper_h):
    """接口 1.4：不接受前端传 warehouse_id 绕过数据权限。"""
    r = client.get("/api/v1/locations?warehouse_id=3", headers=keeper_h)
    assert r.status_code == 403
    assert r.json()["code"] == "WMS-4030"


def test_仓管员库位列表不含未分配仓库(client, keeper_h):
    """不传 warehouse_id 时也只返回可见仓库下的库位。"""
    d = client.get("/api/v1/locations?page=1&page_size=100", headers=keeper_h).json()["data"]
    assert d["total"] == 24, "WH-001 + WH-002 各 12 个库位"
    assert {i["warehouse_name"] for i in d["items"]} == {"1#原料仓", "2#成品仓"}


def test_主管库位列表含全部仓库(client):
    h = login(client, "supervisor")
    d = client.get("/api/v1/locations?page=1&page_size=100", headers=h).json()["data"]
    assert d["total"] == 40


def test_未分配任何仓库的账号看不到数据(client, ah):
    """新建一个不分配仓库的检验员 → 列表为空，但不能报错。"""
    uid = client.post("/api/v1/users", headers={**ah, "X-Client-Op-Id": op_id()},
                      json={"username": "noscope", "name": "无范围检验员",
                            "password": "noscope", "role": "INSPECTOR"}).json()["data"]["id"]
    # 检验员不分配仓库会被 assign_roles 拒绝，所以这里直接改 user_warehouse
    from app.core.db import SessionLocal
    from app.domain.models import UserWarehouse

    with SessionLocal() as s:
        s.query(UserWarehouse).filter(UserWarehouse.user_id == uid).delete()
        s.commit()

    h = login(client, "noscope")
    assert client.get("/api/v1/warehouses", headers=h).json()["data"] == []
    d = client.get("/api/v1/locations?page=1&page_size=20", headers=h).json()["data"]
    assert d["total"] == 0
