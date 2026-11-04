# -*- coding: utf-8 -*-
"""问数测试（T-04-6 / 接口 55 / X01）。

重点验证 ADR-006 的三条：模板出 SQL、guard 拒写、同一问题同一结果。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.ai.nl_query import guard, intent, semantics
from app.core.db import SessionLocal
from app.domain.models import Location, NlQueryLog, Txn
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


# ---------------------------------------------------------------- guard
@pytest.mark.parametrize("sql", [
    "UPDATE inventory SET qty = 0 LIMIT 1",
    "DELETE FROM txn LIMIT 1",
    "SELECT 1; DROP TABLE txn",
    "SELECT 1 -- 注释",
    "SELECT * FROM txn",
    "SELECT * FROM txn LIMIT 99999",
    "SELECT * FROM information_schema.tables LIMIT 1",
    "",
])
def test_guard拒绝危险SQL(sql):
    ok, reason = guard.validate(sql)
    assert not ok and reason


def test_guard放行合法查询():
    ok, _ = guard.validate("SELECT DATE(created_at) d, COUNT(*) FROM txn LIMIT 500")
    assert ok


def test_guard自动补LIMIT():
    assert guard.enforce_limit("SELECT 1").endswith("LIMIT 5000")


# ---------------------------------------------------------------- 意图
def test_解析PRD示例问题():
    r = intent.parse("上周 A3288 出了多少台？")
    assert r["metric"] == "outbound_qty"
    assert r["params"]["sku_code"] == "A3288"


def test_解析近N天():
    now = datetime(2026, 11, 4, 12, 0, 0)
    r = intent.parse("近 3 天入库多少", now=now)
    assert r["metric"] == "inbound_qty"
    assert (now - r["params"]["start"]).days == 2


def test_解析低库存优先于库存():
    """“低库存”必须先命中 low_stock，不能被泛化的“库存”吃掉。"""
    assert intent.parse("哪些物料低库存")["metric"] == "low_stock"
    assert intent.parse("现在库存多少")["metric"] == "inventory_qty"


def test_未命中指标返回None():
    assert intent.parse("今天天气怎么样")["metric"] is None


def test_编码抽取只认编码形态():
    assert intent.parse("A3288 出库")["params"]["sku_code"] == "A3288"
    assert intent.parse("WMS 系统出库多少")["params"]["sku_code"] is None


# ---------------------------------------------------------------- 语义层
def test_数据权限注入到SQL():
    p = semantics.Params(start=datetime.now(), end=datetime.now(), warehouse_ids=[1, 2])
    sql = semantics.outbound_qty(p).sql
    assert "l.warehouse_id IN (1,2)" in sql


def test_主管不限仓库时不注入过滤():
    p = semantics.Params(start=datetime.now(), end=datetime.now(), warehouse_ids=None)
    assert "warehouse_id IN" not in semantics.outbound_qty(p).sql


def test_空仓库范围返回空结果():
    p = semantics.Params(start=datetime.now(), end=datetime.now(), warehouse_ids=[])
    assert "1=0" in semantics.outbound_qty(p).sql


def test_模板SQL必须过guard():
    p = semantics.Params(start=datetime.now(), end=datetime.now(), warehouse_ids=None)
    for m in semantics.METRICS:
        sql = guard.enforce_limit(m.builder(p).sql)
        ok, reason = guard.validate(sql)
        assert ok, f"{m.key} 的模板没过 guard：{reason}"


# ---------------------------------------------------------------- 接口
def test_未命中模板不编SQL(seeded, client, ah):
    r = _post(client, "/api/v1/ai/query", ah, {"question": "今天天气怎么样"})
    d = r.json()["data"]
    assert d["metric"] is None and d["sql"] is None
    assert "暂无数据" in d["conclusion"]

    with SessionLocal() as s:
        row = s.execute(select(NlQueryLog).order_by(NlQueryLog.id.desc())).scalars().first()
        assert row.metric is None and row.rejected is False


def test_同一问题两次结果一致_AC_AI_09(seeded, client, ah, wh1_location_id):
    with SessionLocal() as s:
        apply_many(s, [Move("PRODUCT", 1, wh1_location_id, 5)],
                   biz_type="SALES_OUT", biz_no="NQ-1", operator_id=1)
        s.commit()

    q = {"question": "近7天出库多少"}
    a = _post(client, "/api/v1/ai/query", ah, q).json()["data"]
    b = _post(client, "/api/v1/ai/query", ah, q).json()["data"]
    assert a["sql"] == b["sql"], "同一问题必须同一条 SQL"
    assert a["table"]["rows"] == b["table"]["rows"]
    assert a["metric"] == "outbound_qty"


def test_问数落日志(seeded, client, ah):
    _post(client, "/api/v1/ai/query", ah, {"question": "近7天入库多少"})
    with SessionLocal() as s:
        n = s.execute(select(func.count()).select_from(NlQueryLog)).scalar()
    assert n >= 1


def test_仓管员查不到未授权仓库_AC_AI_12(seeded, client, kh, wh3_id):
    """在 WH-003（仓管员未被分配）造一笔出库，仓管员问数应看不到。"""
    with SessionLocal() as s:
        loc = s.execute(select(Location).where(
            Location.warehouse_id == wh3_id).limit(1)).scalar_one()
        # 先入 9 再出 9：出库流水是负增量
        apply_many(s, [Move("PRODUCT", 1, loc.id, 9)],
                   biz_type="PURCHASE_IN", biz_no="NQ-WH3-IN", operator_id=1)
        apply_many(s, [Move("PRODUCT", 1, loc.id, -9)],
                   biz_type="SALES_OUT", biz_no="NQ-WH3", operator_id=1)
        s.commit()

    admin = _post(client, "/api/v1/ai/query", login(client, "admin"),
                  {"question": "近7天出库多少"}).json()["data"]
    keeper = _post(client, "/api/v1/ai/query", kh,
                   {"question": "近7天出库多少"}).json()["data"]
    admin_total = sum(r[1] for r in admin["table"]["rows"]) if admin["table"]["rows"] else 0
    keeper_total = sum(r[1] for r in keeper["table"]["rows"]) if keeper["table"]["rows"] else 0
    assert admin_total >= 9
    assert keeper_total < admin_total, "仓管员不该看到未授权仓库的数据"
    assert "warehouse_id IN" in keeper["sql"]


def test_问数开关关闭(seeded, client, ah):
    client.put("/api/v1/sys-configs", headers={**ah, "X-Client-Op-Id": str(uuid.uuid4())},
               json={"cfg_key": "query_enabled", "cfg_value": "false", "value_type": "BOOL"})
    r = _post(client, "/api/v1/ai/query", ah, {"question": "近7天入库多少"})
    assert r.json()["code"] == "WMS-4221"
    assert "关闭" in r.json()["message"]


def test_问数返回口径说明(seeded, client, ah):
    d = _post(client, "/api/v1/ai/query", ah, {"question": "近7天入库多少"}).json()["data"]
    assert d["caliber"]
    assert d["table"]["columns"] == ["日期", "入库数量", "单据数"]
    assert d["row_count"] == len(d["table"]["rows"])
