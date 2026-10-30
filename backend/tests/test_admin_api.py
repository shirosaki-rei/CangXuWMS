# -*- coding: utf-8 -*-
"""账号与权限接口测试（T-00-11 交付物，接口 22–24、48–51）。"""
from __future__ import annotations

import pytest
import uuid

from app.core.db import SessionLocal
from app.core.redis import rds
from app.domain.models import User, UserWarehouse

def op_id() -> str:
    """每次写请求都要新的 client_op_id，否则会被幂等中间件判为重放。"""
    return str(uuid.uuid4())




def _h(client, username="admin") -> dict:
    cap = client.get("/api/v1/auth/captcha").json()["data"]
    r = client.post("/api/v1/auth/login",
                    json={"username": username, "password": username,
                          "captcha_id": cap["captcha_id"],
                          "captcha": rds.get(f"captcha:{cap['captcha_id']}")})
    assert r.json()["code"] == "0", r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture
def ah(client):
    return _h(client, "admin")


NEW_USER = {"username": "testkeeper", "name": "测试仓管员", "password": "abc12345",
            "phone": "13900001111", "role": "KEEPER"}


def test_账号列表手机号掩码(client, ah, wh1_id, wh2_id):
    users = client.get("/api/v1/users", headers=ah).json()["data"]
    assert len(users) == 5
    wj = next(u for u in users if u["username"] == "wangjf")
    assert wj["phone"] == "138****5678"
    assert sorted(wj["warehouse_ids"]) == sorted([wh1_id, wh2_id])


def test_新增账号(client, ah):
    r = client.post("/api/v1/users", headers={**ah, "X-Client-Op-Id": op_id()}, json=NEW_USER)
    assert r.json()["code"] == "0"
    uid = r.json()["data"]["id"]
    users = client.get("/api/v1/users", headers=ah).json()["data"]
    assert next(u for u in users if u["id"] == uid)["username"] == "testkeeper"


def test_账号名重复被拒(client, ah):
    assert client.post("/api/v1/users", headers={**ah, "X-Client-Op-Id": op_id()},
                       json=NEW_USER).json()["code"] == "0"
    r = client.post("/api/v1/users",
                    headers={**ah, "X-Client-Op-Id": op_id()},
                    json=NEW_USER)
    assert r.json()["code"] == "WMS-4093"


def test_密码不符合长度被拒(client, ah):
    r = client.post("/api/v1/users", headers={**ah, "X-Client-Op-Id": op_id()},
                    json={**NEW_USER, "username": "shortpwd", "password": "123"})
    assert r.status_code == 400
    assert r.json()["data"]["fields"].get("password")


def test_重置密码后旧密码失效(client, ah):
    uid = client.post("/api/v1/users", headers={**ah, "X-Client-Op-Id": op_id()},
                      json=NEW_USER).json()["data"]["id"]
    r = client.put(f"/api/v1/users/{uid}",
                   headers={**ah, "X-Client-Op-Id": op_id()},
                   json={"password": "newpass123"})
    assert r.json()["code"] == "0"

    # 旧密码登不进去
    cap = client.get("/api/v1/auth/captcha").json()["data"]
    r = client.post("/api/v1/auth/login",
                    json={"username": "testkeeper", "password": "abc12345",
                          "captcha_id": cap["captcha_id"],
                          "captcha": rds.get(f"captcha:{cap['captcha_id']}")})
    assert r.json()["code"] == "WMS-4221"
    # 新密码可以
    cap = client.get("/api/v1/auth/captcha").json()["data"]
    r = client.post("/api/v1/auth/login",
                    json={"username": "testkeeper", "password": "newpass123",
                          "captcha_id": cap["captcha_id"],
                          "captcha": rds.get(f"captcha:{cap['captcha_id']}")})
    assert r.json()["code"] == "0"


def test_停用账号后不能登录(client, ah):
    uid = client.post("/api/v1/users", headers={**ah, "X-Client-Op-Id": op_id()},
                      json=NEW_USER).json()["data"]["id"]
    r = client.put(f"/api/v1/users/{uid}",
                   headers={**ah, "X-Client-Op-Id": op_id()},
                   json={"status": "DISABLED"})
    assert r.json()["code"] == "0"
    cap = client.get("/api/v1/auth/captcha").json()["data"]
    r = client.post("/api/v1/auth/login",
                    json={"username": "testkeeper", "password": "abc12345",
                          "captcha_id": cap["captcha_id"],
                          "captcha": rds.get(f"captcha:{cap['captcha_id']}")})
    assert r.json()["code"] == "WMS-4030"


def test_分配角色与数据权限立即生效(client, ah, wh1_id, wh3_id):
    uid = client.post("/api/v1/users", headers={**ah, "X-Client-Op-Id": op_id()},
                      json=NEW_USER).json()["data"]["id"]

    # 仓管员不分配仓库 → 拒绝
    r = client.post(f"/api/v1/users/{uid}/roles",
                    headers={**ah, "X-Client-Op-Id": op_id()}, json={"role": "KEEPER"})
    assert r.json()["code"] == "WMS-4001"
    assert "仓库" in r.json()["message"]

    r = client.post(f"/api/v1/users/{uid}/roles", headers={**ah, "X-Client-Op-Id": op_id()},
                    json={"role": "KEEPER", "warehouse_ids": [wh3_id]})
    assert r.json()["code"] == "0"

    # 登录后只看得见 WH-003
    cap = client.get("/api/v1/auth/captcha").json()["data"]
    r = client.post("/api/v1/auth/login",
                    json={"username": "testkeeper", "password": "abc12345",
                          "captcha_id": cap["captcha_id"],
                          "captcha": rds.get(f"captcha:{cap['captcha_id']}")})
    assert r.json()["code"] == "0"
    me = client.get("/api/v1/auth/me", headers={
        "Authorization": f"Bearer {r.json()['data']['access_token']}"}).json()["data"]
    assert [w["id"] for w in me["warehouses"]] == [wh3_id]

    # 改成主管 → 见全部
    r = client.post(f"/api/v1/users/{uid}/roles",
                    headers={**ah, "X-Client-Op-Id": op_id()},
                    json={"role": "SUPERVISOR", "warehouse_ids": []})
    assert r.json()["code"] == "0"
    cap = client.get("/api/v1/auth/captcha").json()["data"]
    r = client.post("/api/v1/auth/login",
                    json={"username": "testkeeper", "password": "abc12345",
                          "captcha_id": cap["captcha_id"],
                          "captcha": rds.get(f"captcha:{cap['captcha_id']}")})
    me = client.get("/api/v1/auth/me", headers={
        "Authorization": f"Bearer {r.json()['data']['access_token']}"}).json()["data"]
    assert len(me["warehouses"]) == 3


def test_分配不存在的仓库被拒(client, ah):
    uid = client.post("/api/v1/users", headers={**ah, "X-Client-Op-Id": op_id()},
                      json=NEW_USER).json()["data"]["id"]
    r = client.post(f"/api/v1/users/{uid}/roles", headers={**ah, "X-Client-Op-Id": op_id()},
                    # 9999 这个仓库 id 必然不存在
                    json={"role": "KEEPER", "warehouse_ids": [9999]})
    assert r.json()["code"] == "WMS-4001"
    assert "不存在" in r.json()["message"]


def test_重复分配幂等(client, ah, wh1_id, wh2_id):
    uid = client.post("/api/v1/users", headers={**ah, "X-Client-Op-Id": op_id()},
                      json=NEW_USER).json()["data"]["id"]
    for op in ("f1", "f2"):
        r = client.post(f"/api/v1/users/{uid}/roles",
                        headers={**ah, "X-Client-Op-Id": op}, json={
                            "role": "KEEPER", "warehouse_ids": [wh1_id, wh2_id, wh1_id]})
        assert r.json()["code"] == "0"
    with SessionLocal() as s:
        rows = s.query(UserWarehouse).filter(UserWarehouse.user_id == uid).all()
    assert len(rows) == 2, "重复仓库必须去重"


def test_角色清单与权限一致(client, ah):
    roles = client.get("/api/v1/roles", headers=ah).json()["data"]
    assert len(roles) == 5
    admin = next(r for r in roles if r["value"] == "ADMIN")
    assert "system:manage" in admin["permissions"]
    keeper = next(r for r in roles if r["value"] == "KEEPER")
    assert "system:manage" not in keeper["permissions"]
    assert "inbound:exec" in keeper["permissions"]


def test_权限矩阵与PRD一致(client, ah):
    rows = client.get("/api/v1/permission-matrix", headers=ah).json()["data"]["rows"]
    assert len(rows) == 17
    by_key = {r["key"]: r for r in rows}
    assert by_key["inventory:view"]["KEEPER"] == "✅"
    assert by_key["inventory:view"]["INSPECTOR"] == "✅"
    assert by_key["system:manage"]["ADMIN"] == "✅"
    assert by_key["system:manage"]["SUPERVISOR"] == "—"
    assert by_key["ai:query"]["KEEPER"] == "仅本仓"
    assert by_key["ai:query"]["SUPERVISOR"] == "全部仓库"


def test_规则配置读写_BR026(client, ah):
    r = client.put("/api/v1/sys-configs", headers={**ah, "X-Client-Op-Id": op_id()},
                   json={"cfg_key": "over_receive_ratio", "cfg_value": "0.08",
                         "value_type": "DECIMAL", "remark": "测试改阈值"})
    assert r.json()["code"] == "0"
    cfgs = {c["cfg_key"]: c for c in client.get("/api/v1/sys-configs", headers=ah).json()["data"]}
    assert cfgs["over_receive_ratio"]["cfg_value"] == "0.08"
    assert cfgs["over_receive_ratio"]["remark"] == "测试改阈值"
    # 种子里的 10 项都在
    assert len(cfgs) == 10


def test_配置读取顺序_SUPPLIER优先(client, ah):
    from app.service.admin_service import get_config

    with SessionLocal() as s:
        assert get_config(s, "over_receive_ratio", "0.05") == "0.05"
    client.put("/api/v1/sys-configs", headers={**ah, "X-Client-Op-Id": op_id()},
               json={"cfg_key": "over_receive_ratio", "cfg_value": "0.15",
                     "value_type": "DECIMAL", "scope": "SUPPLIER", "scope_id": 1})
    with SessionLocal() as s:
        assert get_config(s, "over_receive_ratio", scope_id=1) == "0.15", "供应商覆盖优先"
        assert get_config(s, "over_receive_ratio", scope_id=999) == "0.05", "未覆盖回退全局"


def test_SUPPLIER作用域必须填scope_id(client, ah):
    r = client.put("/api/v1/sys-configs", headers={**ah, "X-Client-Op-Id": op_id()},
                   json={"cfg_key": "over_receive_ratio", "cfg_value": "0.15",
                         "value_type": "DECIMAL", "scope": "SUPPLIER"})
    assert r.json()["code"] == "WMS-4001"


def test_非管理员不能访问账号接口(client):
    headers = _h(client, "supervisor")
    r = client.get("/api/v1/users", headers=headers)
    assert r.status_code == 403
    assert r.json()["code"] == "WMS-4030"
