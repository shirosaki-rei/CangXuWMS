# -*- coding: utf-8 -*-
"""来料检验测试（T-01-5，接口 11/12/34/35/36，页面 P14/A05）。

覆盖：扫码推进状态、判定结果与不合格必填原因、超收阈值（BR-005/023）、
生成入库单与拆分多次入库、BR-004 前置条件。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.domain.models import (
    InboundOrder,
    Inspection,
    InspectionItem,
    Material,
    Supplier,
)

from tests.conftest import login

MATERIAL = "BAT-LIPO-4500-003"     # JY20260127001 的物料，计划 500
MATERIAL2 = "DSP-AMOLED-67-FULL"   # JY20260127002 的物料，计划 200，已检合格


def _post(client, path, headers, json=None):
    return client.post(path, headers={**headers, "X-Client-Op-Id": str(uuid.uuid4())},
                       json=json)


@pytest.fixture
def ah(client):
    return login(client, "admin")


@pytest.fixture
def ih(client):
    """检验员。"""
    return login(client, "liq")


@pytest.fixture
def pending_inspection(seeded):
    """待检检验单 JY20260127001（计划 500）。"""
    with SessionLocal() as s:
        iid = s.execute(select(Inspection.id).where(
            Inspection.no == "JY20260127001")).scalar_one()
        mat = s.execute(select(Material.id).where(Material.code == MATERIAL)).scalar_one()
    return {"inspection_id": iid, "material_id": mat, "plan_qty": 500}


def _detail(client, ah, iid):
    return client.get(f"/api/v1/inspections/{iid}", headers=ah).json()["data"]


# ---------------------------------------------------------------- 列表与详情
def test_检验单列表与筛选(client, ah):
    d = client.get("/api/v1/inspections", headers=ah).json()["data"]
    assert d["total"] == 2
    by_no = {i["no"]: i for i in d["items"]}
    assert by_no["JY20260127001"]["status_label"] == "待检"
    assert by_no["JY20260127002"]["result_label"] == "合格"

    d = client.get("/api/v1/inspections?status=DONE", headers=ah).json()["data"]
    assert d["total"] == 1
    d = client.get("/api/v1/inspections?result=FAIL", headers=ah).json()["data"]
    assert d["total"] == 0


def test_详情带超收阈值(client, ah):
    with SessionLocal() as s:
        iid = s.execute(select(Inspection.id).where(
            Inspection.no == "JY20260127001")).scalar_one()
    d = _detail(client, ah, iid)
    assert d["plan_qty"] == 500 and d["actual_qty"] == 0
    assert d["supplier_name"] == "中兴通讯股份有限公司"
    # ZTE 没有覆盖值，用全局默认 0.05
    assert d["over_receive_ratio"] == "0.05"


def test_供应商覆盖阈值优先_BR023(client, ah):
    """sys_config 的全局默认是 0.05，供应商档案覆盖后必须优先。"""
    with SessionLocal() as s:
        s.add(Supplier(code="GYS-TEST-009", name="阈值覆盖测试",
                       over_receive=__import__("decimal").Decimal("0.12")))
        s.commit()
        sid = s.execute(select(Supplier.id).where(
            Supplier.code == "GYS-TEST-009")).scalar_one()
        mat = s.execute(select(Material.id).limit(1)).scalar_one()
        insp = Inspection(no="JY20260127003", supplier_id=sid, status="PENDING",
                          plan_qty=100, actual_qty=0, creator_id=1)
        s.add(insp)
        s.flush()
        s.add(InspectionItem(inspection_id=insp.id, material_id=mat,
                             plan_qty=100, actual_qty=0))
        s.commit()
        iid = insp.id
    d = _detail(client, ah, iid)
    assert d["over_receive_ratio"] == "0.12", "供应商覆盖值必须优先于全局默认"


# ---------------------------------------------------------------- 扫码
def test_扫码推进到检验中(pending_inspection, client, ih):
    r = _post(client, f"/api/v1/inspections/{pending_inspection['inspection_id']}/scan", ih,
              {"material_id": pending_inspection["material_id"], "actual_qty": 120,
               "barcode": "BC-001"})
    d = r.json()["data"]
    assert d["status"] == "CHECKING" and d["scanned"] == 120
    assert d["plan_qty"] == 500


def test_扫码累加同一条码(pending_inspection, client, ah, ih):
    iid, mat = pending_inspection["inspection_id"], pending_inspection["material_id"]
    for q in (100, 50):
        _post(client, f"/api/v1/inspections/{iid}/scan", ih,
              {"material_id": mat, "actual_qty": q, "barcode": "BC-SAME"})
    d = _detail(client, ah, iid)
    item = next(i for i in d["items"] if i["barcode"] == "BC-SAME")
    assert item["actual_qty"] == 150, "同物料同条码要累加，不新开一行"


def test_已判定后不能再扫码(client, ah, ih):
    with SessionLocal() as s:
        iid = s.execute(select(Inspection.id).where(
            Inspection.no == "JY20260127002")).scalar_one()
    r = _post(client, f"/api/v1/inspections/{iid}/scan", ih,
              {"material_id": 1, "actual_qty": 1})
    assert r.json()["code"] == "WMS-4092"


def test_物料不存在被拒(pending_inspection, client, ih):
    r = _post(client, f"/api/v1/inspections/{pending_inspection['inspection_id']}/scan", ih,
              {"material_id": 999999, "actual_qty": 1})
    assert r.json()["code"] == "WMS-4001"


# ---------------------------------------------------------------- 判定
def test_判定合格(pending_inspection, client, ih):
    iid = pending_inspection["inspection_id"]
    _post(client, f"/api/v1/inspections/{iid}/scan", ih,
          {"material_id": pending_inspection["material_id"], "actual_qty": 500})
    r = _post(client, f"/api/v1/inspections/{iid}/judge", ih, {"result": "PASS"})
    d = r.json()["data"]
    assert d["result"] == "PASS" and d["status"] == "DONE"
    assert d["result_label"] == "合格"
    # 合格时明细应全部标记合格
    with SessionLocal() as s:
        rows = s.execute(select(InspectionItem).where(
            InspectionItem.inspection_id == iid)).scalars().all()
        assert all(r.qualified for r in rows)


def test_判定不合格必须填原因(pending_inspection, client, ih):
    iid = pending_inspection["inspection_id"]
    _post(client, f"/api/v1/inspections/{iid}/scan", ih,
          {"material_id": pending_inspection["material_id"], "actual_qty": 500})
    r = _post(client, f"/api/v1/inspections/{iid}/judge", ih, {"result": "FAIL"})
    assert r.json()["code"] == "WMS-4001"
    assert "原因" in r.json()["message"]

    r = _post(client, f"/api/v1/inspections/{iid}/judge", ih,
              {"result": "FAIL", "fail_reason": "来料批量划伤，退回供应商"})
    assert r.json()["data"]["result"] == "FAIL"


def test_超收超阈值转人工_BR005(pending_inspection, client, ih):
    """计划 500、阈值 5% → 上限 525。扫 600 判定超收必须被拒。"""
    iid = pending_inspection["inspection_id"]
    _post(client, f"/api/v1/inspections/{iid}/scan", ih,
          {"material_id": pending_inspection["material_id"], "actual_qty": 600})
    r = _post(client, f"/api/v1/inspections/{iid}/judge", ih, {"result": "OVER_PASS"})
    assert r.json()["code"] == "WMS-4221"
    assert "阈值" in r.json()["message"]
    assert r.json()["data"]["limit"] == 525


def test_超收在阈值内放行_BR005(pending_inspection, client, ih):
    """计划 500、阈值 5% → 上限 525。扫 520 判定超收应放行。"""
    iid = pending_inspection["inspection_id"]
    _post(client, f"/api/v1/inspections/{iid}/scan", ih,
          {"material_id": pending_inspection["material_id"], "actual_qty": 520})
    r = _post(client, f"/api/v1/inspections/{iid}/judge", ih, {"result": "OVER_PASS"})
    assert r.json()["code"] == "0"


def test_不能重复判定(client, ah, ih):
    with SessionLocal() as s:
        iid = s.execute(select(Inspection.id).where(
            Inspection.no == "JY20260127002")).scalar_one()
    r = _post(client, f"/api/v1/inspections/{iid}/judge", ih, {"result": "PASS"})
    assert r.json()["code"] == "WMS-4092"


# ---------------------------------------------------------------- 生成入库单
def test_生成采购入库单(pending_inspection, client, ah, ih):
    """JY20260127002 的合格数已被种子的 PR20260127001 占用，这里用 JY20260127001。"""
    iid = pending_inspection["inspection_id"]
    _post(client, f"/api/v1/inspections/{iid}/scan", ih,
          {"material_id": pending_inspection["material_id"], "actual_qty": 500})
    _post(client, f"/api/v1/inspections/{iid}/judge", ih, {"result": "PASS"})
    r = _post(client, f"/api/v1/inspections/{iid}/gen-inbound", ih, {})
    d = r.json()["data"]
    assert d["plan_qty"] == 500, "默认取剩余合格数"
    assert d["no"].startswith("PR")
    assert d["remain"] == 0

    # 入库单应关联检验单号
    with SessionLocal() as s:
        o = s.execute(select(InboundOrder).where(
            InboundOrder.no == d["no"])).scalar_one()
        assert o.source_no == "JY20260127001"
        assert o.type == "PURCHASE" and o.status == "PENDING"


def test_拆分多次入库(pending_inspection, client, ah, ih):
    """允许一个检验单拆成多次入库。"""
    iid = pending_inspection["inspection_id"]
    _post(client, f"/api/v1/inspections/{iid}/scan", ih,
          {"material_id": pending_inspection["material_id"], "actual_qty": 500})
    _post(client, f"/api/v1/inspections/{iid}/judge", ih, {"result": "PASS"})
    r1 = _post(client, f"/api/v1/inspections/{iid}/gen-inbound", ih, {"qty": 120})
    assert r1.json()["data"]["remain"] == 380, "500 - 120"
    r2 = _post(client, f"/api/v1/inspections/{iid}/gen-inbound", ih, {"qty": 380})
    assert r2.json()["data"]["remain"] == 0, "500 - 120 - 380"
    # 第三次没有剩余了
    r3 = _post(client, f"/api/v1/inspections/{iid}/gen-inbound", ih, {})
    assert r3.json()["code"] == "WMS-4221"


def test_入库数量超过剩余被拒(pending_inspection, client, ah, ih):
    iid = pending_inspection["inspection_id"]
    _post(client, f"/api/v1/inspections/{iid}/scan", ih,
          {"material_id": pending_inspection["material_id"], "actual_qty": 500})
    _post(client, f"/api/v1/inspections/{iid}/judge", ih, {"result": "PASS"})
    r = _post(client, f"/api/v1/inspections/{iid}/gen-inbound", ih, {"qty": 999})
    assert r.json()["code"] == "WMS-4221"
    assert r.json()["data"]["remain"] == 500


def test_未判定不能生成入库单(pending_inspection, client, ih):
    r = _post(client,
              f"/api/v1/inspections/{pending_inspection['inspection_id']}/gen-inbound", ih, {})
    assert r.json()["code"] == "WMS-4221"
    assert "判定" in r.json()["message"]


def test_不合格不能生成入库单(client, ah, ih):
    with SessionLocal() as s:
        iid = s.execute(select(Inspection.id).where(
            Inspection.no == "JY20260127001")).scalar_one()
        mat = s.execute(select(Material.id).where(Material.code == MATERIAL)).scalar_one()
    _post(client, f"/api/v1/inspections/{iid}/scan", ih,
          {"material_id": mat, "actual_qty": 500})
    _post(client, f"/api/v1/inspections/{iid}/judge", ih,
          {"result": "FAIL", "fail_reason": "批量不良，整批退回"})
    r = _post(client, f"/api/v1/inspections/{iid}/gen-inbound", ih, {})
    assert r.json()["code"] == "WMS-4221"


# ---------------------------------------------------------------- 权限
def test_仓管员不能判定(pending_inspection, client):
    kh = login(client, "wangjf")
    r = _post(client, f"/api/v1/inspections/{pending_inspection['inspection_id']}/judge", kh,
              {"result": "PASS"})
    assert r.status_code == 403
    assert r.json()["code"] == "WMS-4030"
