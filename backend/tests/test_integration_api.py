# -*- coding: utf-8 -*-
"""集成端签名与 MES 推送测试（T-00-12，接口 62 / 接口文档 4.1–4.2）。"""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.integration_auth import sign
from app.domain.models import ApiClient, Inspection, InspectionItem

APP_KEY = "mes-prod"
APP_SECRET = "mes-secret-change-me"


def _headers(body: bytes, *, key: str = APP_KEY, secret: str = APP_SECRET,
             ts: int | None = None, bad_sign: bool = False) -> dict:
    ts = ts if ts is not None else int(time.time())
    sig = sign(secret, key, str(ts), body)
    if bad_sign:
        sig = "0" * 64
    return {
        "Content-Type": "application/json; charset=utf-8",
        "X-App-Key": key,
        "X-Timestamp": str(ts),
        "X-Sign": sig,
    }


def _push(client, body: dict, headers: dict):
    import json

    return client.post("/api/v1/integration/inspections",
                       content=json.dumps(body).encode(), headers=headers)


VALID = {
    "no": "JY20260203001",
    "version": 1,
    "supplier_code": "GYS-ZTE-001",
    "logistics_no": "WL20260203001",
    "plate_no": "京C12345",
    "items": [{"material_code": "BAT-LIPO-4500-003", "plan_qty": 300}],
}


def _count(no: str) -> int:
    with SessionLocal() as s:
        return int(s.execute(
            select(func.count()).select_from(Inspection).where(Inspection.no == no)
        ).scalar())


# ---------------------------------------------------------------- 签名
def test_合法签名推送成功(client):
    import json

    body = json.dumps(VALID).encode()
    r = _push(client, VALID, _headers(body))
    assert r.json()["code"] == "0", r.text
    assert r.json()["data"]["no"] == "JY20260203001"
    assert _count("JY20260203001") == 1


def test_缺签名头被拒_4011(client):
    r = client.post("/api/v1/integration/inspections", json=VALID)
    assert r.status_code == 401
    assert r.json()["code"] == "WMS-4011"


def test_签名错误被拒_4011(client):
    import json

    body = json.dumps(VALID).encode()
    r = _push(client, VALID, _headers(body, bad_sign=True))
    assert r.status_code == 401
    assert r.json()["code"] == "WMS-4011"
    assert _count("JY20260203001") == 0


def test_密钥不对被拒(client):
    import json

    body = json.dumps(VALID).encode()
    r = _push(client, VALID, _headers(body, secret="wrong-secret"))
    assert r.status_code == 401
    assert r.json()["code"] == "WMS-4011"


def test_时间戳超时被拒_防重放(client):
    import json

    body = json.dumps(VALID).encode()
    old = int(time.time()) - 400  # 超过 300 秒容差
    r = _push(client, VALID, _headers(body, ts=old))
    assert r.status_code == 401
    assert r.json()["code"] == "WMS-4011"
    assert "偏差" in r.json()["message"]


def test_app_key不存在不暴露账号是否存在(client):
    import json

    body = json.dumps(VALID).encode()
    r = _push(client, VALID, _headers(body, key="not-exist"))
    assert r.status_code == 401
    # 与「签名错误」同一句话，不让对端探到账号是否存在
    assert r.json()["message"] == "签名错误"


def test_停用的集成账号被拒(client, seeded):
    import json

    with SessionLocal() as s:
        c = s.execute(select(ApiClient).where(ApiClient.app_key == APP_KEY)).scalar_one()
        c.status = "DISABLED"
        s.commit()
    body = json.dumps(VALID).encode()
    r = _push(client, VALID, _headers(body))
    assert r.status_code == 401


def test_签名对body敏感_改动即失效(client):
    """改一个字符签名就对不上——这是 HMAC 的意义。"""
    import json

    body = json.dumps(VALID).encode()
    tampered = {**VALID, "logistics_no": "WL-HACKED"}
    r = _push(client, tampered, _headers(body))
    assert r.status_code == 401


# ---------------------------------------------------------------- 幂等
def test_重复推送返回首次结果_WMS4091(client):
    import json

    body = json.dumps(VALID).encode()
    h = _headers(body)
    r1 = _push(client, VALID, h)
    assert r1.json()["code"] == "0"
    first_id = r1.json()["data"]["id"]

    r2 = _push(client, VALID, h)
    assert r2.json()["code"] == "WMS-4091"
    assert r2.json()["data"]["id"] == first_id
    assert _count("JY20260203001") == 1, "不能产生重复单据"


def test_推送内容落库(client):
    import json

    body = json.dumps(VALID).encode()
    _push(client, VALID, _headers(body))
    with SessionLocal() as s:
        insp = s.execute(select(Inspection).where(
            Inspection.no == "JY20260203001")).scalar_one()
        assert insp.supplier_id is not None
        assert insp.plan_qty == 300
        assert insp.status == "PENDING"
        assert insp.logistics_no == "WL20260203001"
        assert insp.plate_no == "京C12345"
        items = s.execute(
            select(InspectionItem).where(InspectionItem.inspection_id == insp.id)
        ).scalars().all()
        assert len(items) == 1 and items[0].plan_qty == 300


def test_供应商编码未维护被拒(client):
    import json

    bad = {**VALID, "no": "JY20260203002", "supplier_code": "GYS-NOPE"}
    body = json.dumps(bad).encode()
    r = _push(client, bad, _headers(body))
    assert r.json()["code"] == "WMS-4001"
    assert "供应商" in r.json()["message"]


def test_物料编码未维护被拒(client):
    import json

    bad = {**VALID, "no": "JY20260203003",
           "items": [{"material_code": "MAT-NOPE", "plan_qty": 1}]}
    body = json.dumps(bad).encode()
    r = _push(client, bad, _headers(body))
    assert r.json()["code"] == "WMS-4001"
    assert "物料" in r.json()["message"]


def test_集成接口不需要用户JWT(client):
    """集成端与用户端认证分离（架构 6.2 api_client）。"""
    import json

    body = json.dumps(VALID).encode()
    r = _push(client, VALID, _headers(body))
    assert r.json()["code"] == "0"


# ---------------------------------------------------------------- 纯函数
def test_签名函数可复现():
    a = sign("secret", "key", "1769498400", b'{"a":1}')
    b = sign("secret", "key", "1769498400", b'{"a":1}')
    assert a == b and len(a) == 64
    assert a != sign("secret", "key", "1769498400", b'{"a":2}')
    assert a != sign("secret2", "key", "1769498400", b'{"a":1}')
    assert a != sign("secret", "key2", "1769498400", b'{"a":1}')
