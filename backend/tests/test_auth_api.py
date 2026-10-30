# -*- coding: utf-8 -*-
"""认证接口测试（T-00-4 交付物，接口 1–3）。"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.redis import rds
from app.domain.models import User


def _captcha(client) -> tuple[str, str]:
    r = client.get("/api/v1/auth/captcha")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["captcha_id"] and data["image"].startswith("data:image/svg+xml;base64,")
    return data["captcha_id"], rds.get(f"captcha:{data['captcha_id']}")


def _login(client, username="admin", password="admin", captcha=None, cid=None):
    if captcha is None:
        cid, captcha = _captcha(client)
    return client.post("/api/v1/auth/login", json={
        "username": username, "password": password,
        "captcha_id": cid, "captcha": captcha,
    })


def test_验证码是一次性的(client):
    cid, code = _captcha(client)
    assert _login(client, captcha=code, cid=cid).json()["code"] == "0"
    # 同一个 captcha_id 再登一次必须失败
    r = _login(client, captcha=code, cid=cid)
    assert r.json()["code"] == "WMS-4001"
    assert "过期" in r.json()["message"]


def test_登录成功返回令牌与落地页(client):
    r = _login(client)
    body = r.json()
    assert r.status_code == 200 and body["code"] == "0"
    d = body["data"]
    assert d["access_token"] and d["refresh_token"]
    assert d["expires_in"] == 7200 and d["refresh_expires_in"] == 604800
    assert d["user"]["role"] == "ADMIN"
    assert d["landing"] == "/basedata/warehouse"
    assert r.headers["x-trace-id"]


def test_密码错误累加五次锁十分钟(client):
    for i in range(4):
        r = _login(client, password="wrong")
        assert r.json()["code"] == "WMS-4221", i
    r = _login(client, password="wrong")
    assert r.json()["code"] == "WMS-4221"
    assert "锁定" in r.json()["message"]
    # 锁定期内即使密码正确也进不去
    r = _login(client)
    assert r.json()["code"] == "WMS-4221"
    assert r.json()["data"]["locked_until"]


def test_停用账号不能登录(client, db):
    from app.domain.models import User

    u = db.execute(select(User).where(User.username == "wangjf")).scalar_one()
    u.status = "DISABLED"
    db.commit()
    r = _login(client, username="wangjf", password="wangjf")
    assert r.json()["code"] == "WMS-4030"


def test_me返回权限与可见仓库(client, login_as):
    headers = login_as("wangjf")
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.json()["code"] == "0"
    me = r.json()["data"]
    assert me["role"] == "KEEPER"
    assert "inbound:exec" in me["permissions"]
    assert "system:manage" not in me["permissions"]
    assert len(me["warehouses"]) == 2, "仓管员只见被分配的两个仓库"
    assert me["phone"] == "138****5678", "手机号必须掩码"


def test_主管可见全部仓库(client, login_as):
    headers = login_as("supervisor")
    me = client.get("/api/v1/auth/me", headers=headers).json()["data"]
    assert len(me["warehouses"]) == 3


def test_未带token访问受保护接口返回4010(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "WMS-4010"


def test_假token返回4010(client):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401
    assert r.json()["code"] == "WMS-4010"


def test_登出后token立即失效(client, login_as):
    headers = login_as("admin")
    assert client.get("/api/v1/auth/me", headers=headers).json()["code"] == "0"
    assert client.post("/api/v1/auth/logout", headers=headers).json()["code"] == "0"
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 401
    assert r.json()["code"] == "WMS-4010"


def test_refresh能换新access(client):
    r = _login(client)
    refresh = r.json()["data"]["refresh_token"]
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r2.json()["code"] == "0"
    new_access = r2.json()["data"]["access_token"]
    assert new_access != r.json()["data"]["access_token"]
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {new_access}"})
    assert me.json()["code"] == "0"


def test_access_token不能当refresh用(client):
    r = _login(client)
    access = r.json()["data"]["access_token"]
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert r2.json()["code"] == "WMS-4010"


def test_验证码缺失报4001(client):
    r = client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "admin", "captcha_id": "", "captcha": ""})
    assert r.status_code == 400
    assert r.json()["code"] == "WMS-4001"
    assert "fields" in r.json()["data"]


def test_错误码与HTTP状态分离(client):
    """业务错误 HTTP 200，传输/认证错误才用 4xx/5xx（接口文档 1.2）。"""
    assert _login(client, password="wrong").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
