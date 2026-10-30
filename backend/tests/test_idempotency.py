# -*- coding: utf-8 -*-
"""幂等中间件测试（T-00-8 交付物，接口文档 1.3）。"""
from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.core.redis import rds
from app.domain.models import OpLog

OP = "77777777-7777-4777-8777-777777777777"


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


def _create(client, ah, op_id, code="WH-777"):
    return client.post("/api/v1/warehouses", headers={**ah, "X-Client-Op-Id": op_id},
                       json={"code": code, "name": "幂等测试仓", "type": "AUX"})


def test_首次执行落op_log(client, ah, admin_id):
    r = _create(client, ah, OP, "WH-880")
    assert r.json()["code"] == "0"
    with SessionLocal() as s:
        row = s.query(OpLog).filter(OpLog.client_op_id == OP).one()
    assert row.path == "/api/v1/warehouses"
    assert row.result["id"] == r.json()["data"]["id"]
    assert row.user_id == admin_id


def test_同一op_id重放返回首次结果(client, ah):
    r1 = _create(client, ah, OP, "WH-881")
    wid = r1.json()["data"]["id"]

    r2 = _create(client, ah, OP, "WH-882")  # 换了个 code，也不该新建
    assert r2.json()["code"] == "WMS-4091"
    assert r2.json()["data"]["id"] == wid, "必须原样返回首次结果"
    assert r2.status_code == 200, "幂等重放的 HTTP 状态是 200（接口 1.2）"

    with SessionLocal() as s:
        n = s.query(OpLog).filter(OpLog.client_op_id == OP).count()
    assert n == 1
    # 没有产生第二个仓库
    items = client.get("/api/v1/warehouses", headers=ah).json()["data"]
    assert len([i for i in items if i["name"] == "幂等测试仓"]) == 1


def test_不同op_id互不影响(client, ah):
    a = _create(client, ah, "88888888-8888-4888-8888-888888888888", "WH-883")
    b = _create(client, ah, "99999999-9999-4999-8999-999999999999", "WH-884")
    assert a.json()["code"] == "0" and b.json()["code"] == "0"
    assert a.json()["data"]["id"] != b.json()["data"]["id"]


def test_失败不占坑_重试能真正重跑(client, ah):
    """第一次业务失败 → Redis 键被删 → 同 op_id 重试应真正执行。"""
    r = _create(client, ah, OP, "WH-885")  # 成功
    assert r.json()["code"] == "0"

    # 同一个 op_id 但业务上会失败：编码重复
    dup = _create(client, ah, "aaaa1111-1111-4111-8111-111111111111", "WH-885")
    assert dup.json()["code"] == "WMS-4093"
    assert not rds.exists("idem:aaaa1111-1111-4111-8111-111111111111"), "失败必须释放幂等键"

    # 修正 code 后用同一个 op_id 重试 → 真的执行
    r2 = client.post("/api/v1/warehouses",
                     headers={**ah, "X-Client-Op-Id": "aaaa1111-1111-4111-8111-111111111111"},
                     json={"code": "WH-886", "name": "重试成功", "type": "AUX"})
    assert r2.json()["code"] == "0"
    assert r2.json()["data"]["id"] != r.json()["data"]["id"]


def test_op_log是唯一索引兜底(client, ah):
    """Redis 键被清后，DB 唯一索引仍能识别重放。"""
    _create(client, ah, OP, "WH-887")
    rds.delete(f"idem:{OP}")
    r = _create(client, ah, OP, "WH-888")
    assert r.json()["code"] == "WMS-4091"


def test_登录不走幂等(client):
    """登录无 client_op_id，必须放行。"""
    cap = client.get("/api/v1/auth/captcha").json()["data"]
    r = client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "admin",
        "captcha_id": cap["captcha_id"],
        "captcha": rds.get(f"captcha:{cap['captcha_id']}"),
    })
    assert r.json()["code"] == "0"


def test_GET不要求幂等键(client, ah):
    r = client.get("/api/v1/warehouses", headers=ah)
    assert r.json()["code"] == "0"
