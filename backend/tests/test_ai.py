# -*- coding: utf-8 -*-
"""AI 层测试（T-04-2/3/4，接口 52/53/54/56/57）。

分两部分：纯函数（推荐打分 / 路径 / 校验规则）不碰数据库，跑得飞快；
接口部分走 TestClient。
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.ai import check_engine, location_advisor as la, path_solver
from app.ai.check_engine import CheckContext
from app.ai.path_solver import Point
from tests.conftest import login


def _post(client, path, headers, json=None):
    return client.post(path, headers={**headers, "X-Client-Op-Id": str(uuid.uuid4())},
                       json=json)


def _cand(i, *, status="IDLE", type="NORMAL", cap=10, used=0, dist=10.0, same=0):
    return la.Candidate(location_id=i, code=f"A1-01-{i:02d}", type=type, status=status,
                        cap_pallet=cap, used_pallet=used, dist_to_pack=dist,
                        same_sku_pallets=same)


# ---------------------------------------------------------------- 库位推荐
def test_硬约束淘汰锁定与类型不符():
    ctx = la.Context(pallet_count=1, warehouse_id=1, is_dangerous=False)
    cands = [
        _cand(1, status="LOCKED"),
        _cand(2, type="DANGEROUS"),
        _cand(3, cap=5, used=5),          # 超容量
        _cand(4),                          # 唯一合法的
    ]
    out = la.recommend(cands, ctx)
    assert out["primary"]["location_id"] == 4
    assert all(a["location_id"] != 1 for a in out["alternatives"])


def test_危品物料可以进危品库位():
    """危品物料两个库位都合法；让危品库位明显更优，避免并列导致低置信度。"""
    ctx = la.Context(pallet_count=1, warehouse_id=1, is_dangerous=True)
    cands = [_cand(1, type="DANGEROUS", same=5, dist=5), _cand(2, same=0, dist=30)]
    out = la.recommend(cands, ctx)
    assert out["primary"] is not None
    assert out["primary"]["location_id"] == 1


def test_没有任何合法库位时返回原因():
    ctx = la.Context(pallet_count=99, warehouse_id=1)
    out = la.recommend([_cand(1, cap=1)], ctx)
    assert out["primary"] is None
    assert "硬约束" in out["reason"] or "没有" in out["reason"]


def test_聚合度高的库位得分更高():
    ctx = la.Context(pallet_count=1, warehouse_id=1)
    cands = [_cand(1, same=0, dist=10), _cand(2, same=5, dist=10)]
    out = la.recommend(cands, ctx)
    assert out["primary"]["location_id"] == 2


def test_距离近的库位得分更高():
    ctx = la.Context(pallet_count=1, warehouse_id=1)
    cands = [_cand(1, dist=50), _cand(2, dist=5)]
    out = la.recommend(cands, ctx)
    assert out["primary"]["location_id"] == 2


def test_分差过小给低置信度且不给Top1():
    ctx = la.Context(pallet_count=1, warehouse_id=1)
    # 两个几乎一样的库位
    cands = [_cand(1, same=1, dist=10), _cand(2, same=1, dist=10), _cand(3, same=1, dist=10)]
    out = la.recommend(cands, ctx)
    assert out["confidence"] == "LOW"
    assert out["primary"] is None
    assert len(out["alternatives"]) == 3


def test_缺坐标时降级且只给两条理由():
    ctx = la.Context(pallet_count=1, warehouse_id=1, coord_required=True)
    cands = [la.Candidate(i, f"A-{i}", "NORMAL", "IDLE", 10, 0, None, same_sku_pallets=i)
             for i in range(1, 4)]
    out = la.recommend(cands, ctx)
    assert out["degraded"] is True
    if out["primary"]:
        assert len(out["primary"]["reasons"]) == 2


def test_理由不超过三条且不重复():
    ctx = la.Context(pallet_count=1, warehouse_id=1)
    cands = [_cand(1, same=3, dist=12), _cand(2, same=1, dist=20), _cand(3, same=0, dist=30)]
    out = la.recommend(cands, ctx)
    reasons = out["primary"]["reasons"]
    assert 2 <= len(reasons) <= 3
    assert len(set(reasons)) == len(reasons)


# ---------------------------------------------------------------- 路径优化
def test_三点走精确解():
    pts = [Point("S", 0, 0), Point("A", 1, 0), Point("B", 0, 1)]
    r = path_solver.optimize(pts)
    assert r["algorithm"] == "HELD_KARP"
    assert set(r["sequence"]) == {"S", "A", "B"}
    assert r["distance_m"] > 0


def test_十五点走启发式():
    pts = [Point("S", 0, 0)] + [Point(f"A-{i:02d}", i % 5 * 2, i // 5 * 2) for i in range(14)]
    r = path_solver.optimize(pts)
    assert r["algorithm"] == "NN_2OPT"
    assert r["point_count"] == 15


def test_六十点走聚类():
    pts = [Point("S", 0, 0)] + [Point(f"{chr(65 + i % 4)}-{i:03d}", i % 10, i // 10)
                                for i in range(59)]
    r = path_solver.optimize(pts)
    assert r["algorithm"] == "CLUSTER_S"
    assert len(r["sequence"]) == 60


def test_顺序包含全部点且节省不为负():
    pts = [Point("S", 0, 0)] + [Point(f"B-{i:02d}", i * 3, (i % 3) * 4) for i in range(10)]
    r = path_solver.optimize(pts)
    assert sorted(r["sequence"]) == sorted(p.code for p in pts)
    assert r["saved_m"] >= 0
    assert r["distance_m"] <= r["baseline_m"] + 1e-6


def test_空点集不炸():
    r = path_solver.optimize([])
    assert r["point_count"] == 0 and r["algorithm"] == "NONE"


# ---------------------------------------------------------------- 校验规则
def test_R3库位类型不符是阻断():
    ctx = CheckContext(order_type="INBOUND", plan_qty=10, actual_qty=10,
                       items=[{"box_code": "B1"}], mismatch_locations=["A1-01"])
    r = check_engine.r3_location_type(ctx)
    assert r.level == "BLOCK"


def test_R1数量偏差预警():
    ctx = CheckContext(order_type="INBOUND", plan_qty=100, actual_qty=112)
    r = check_engine.r1_qty_deviation(ctx)
    assert r.level == "WARN" and "+12%" in r.title


def test_R4超收在阈值内通过():
    ctx = CheckContext(order_type="INBOUND", plan_qty=100, actual_qty=103)
    assert check_engine.r4_over_receive(ctx).level == "PASS"


def test_R4超收超阈值预警():
    ctx = CheckContext(order_type="INBOUND", plan_qty=100, actual_qty=130)
    assert check_engine.r4_over_receive(ctx).level == "WARN"


def test_R5出库库存不足是阻断():
    ctx = CheckContext(order_type="OUTBOUND", plan_qty=120, actual_qty=120, available=96)
    r = check_engine.r5_stock_available(ctx)
    assert r.level == "BLOCK" and "24" in r.title


def test_R5对入库单跳过且不计入通过():
    ctx = CheckContext(order_type="INBOUND", plan_qty=1, actual_qty=1)
    assert check_engine.r5_stock_available(ctx).level == "SKIP"


def test_R6不计入汇总():
    ctx = CheckContext(order_type="INBOUND", plan_qty=10, actual_qty=10, recent_submits_1h=99)
    results = check_engine.run(ctx)
    s = check_engine.summary(results)
    # R6 是记录级，pass+warn+block 不应包含它
    assert next(r for r in results if r.rule == "R6").level in ("PASS", "LOG")
    assert s["pass"] + s["warn"] + s["block"] + s["timeout"] + s["skipped"] == len(results) - 1


def test_入库单的R5显式跳过():
    """接口 3.6 的示例里入库单返回 R5 SKIP「跳过且不计入通过数」。"""
    ctx = CheckContext(order_type="INBOUND", plan_qty=10, actual_qty=10)
    res = check_engine.run(ctx)
    r5 = next(r for r in res if r.rule == "R5")
    assert r5.level == "SKIP"
    assert {"R1", "R2", "R3", "R4", "R7", "R6"} <= {r.rule for r in res}


def test_出库单的R4跳过且不含R7():
    ctx = CheckContext(order_type="OUTBOUND", plan_qty=10, actual_qty=10, available=99)
    res = check_engine.run(ctx)
    assert next(r for r in res if r.rule == "R4").level == "SKIP"
    assert "R7" not in {r.rule for r in res}
    assert {"R1", "R2", "R3", "R5", "R6"} <= {r.rule for r in res}


def test_盘点单规则集():
    ctx = CheckContext(order_type="STOCKTAKE", total=100, done=88, diff_items=8)
    rules = {r.rule for r in check_engine.run(ctx)}
    assert {"R8", "R9", "R10", "R11", "R6"} <= rules
    results = check_engine.run(ctx)
    r8 = next(r for r in results if r.rule == "R8")
    assert r8.level == "WARN" and "12" in r8.title


def test_盘点差异率超阈值预警():
    ctx = CheckContext(order_type="STOCKTAKE", total=100, done=100, diff_items=9)
    assert check_engine.r9_diff_rate(ctx).level == "WARN"


def test_全部通过时无阻断():
    ctx = CheckContext(order_type="OUTBOUND", plan_qty=10, actual_qty=10,
                       available=100, items=[{"sn": "SN1"}])
    results = check_engine.run(ctx)
    assert not any(r.level == "BLOCK" for r in results)


# ---------------------------------------------------------------- 接口
@pytest.fixture
def ah(client):
    return login(client, "admin")


@pytest.fixture
def kh(client):
    return login(client, "wangjf")


def test_库位推荐接口落建议(seeded, client, kh, wh1_id):
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.domain.models import Product

    with SessionLocal() as s:
        pid = s.execute(select(Product.id).where(Product.code == "A3288")).scalar_one()
    r = _post(client, "/api/v1/ai/locations/recommend", kh,
              {"sku_type": "PRODUCT", "sku_id": pid, "warehouse_id": wh1_id,
               "qty": 10, "pallet_count": 2})
    d = r.json()
    assert d["code"] == "0", r.text
    assert d["data"]["suggestion_id"] > 0
    assert "confidence" in d["data"]


def test_路径优化接口(client, kh):
    r = _post(client, "/api/v1/ai/picking/optimize", kh, {
        "order_type": "SALES",
        "points": [{"location_code": "A1-01-01", "x": 0, "y": 0},
                   {"location_code": "A1-02-01", "x": 2, "y": 0},
                   {"location_code": "B1-01-01", "x": 0, "y": 5}],
    })
    d = r.json()["data"]
    assert d["algorithm"] == "HELD_KARP"
    assert len(d["sequence"]) == 3
    assert d["suggestion_id"] > 0


def test_路径优化缺参数报错(client, kh):
    r = _post(client, "/api/v1/ai/picking/optimize", kh, {"order_type": "SALES"})
    assert r.json()["code"] == "WMS-4001"


def test_提交前校验接口(seeded, client, ah):
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.domain.models import InboundOrder

    with SessionLocal() as s:
        oid = s.execute(select(InboundOrder.id).where(
            InboundOrder.no == "PR20260127001")).scalar_one()
    r = _post(client, f"/api/v1/ai/checks/INBOUND/{oid}", ah, {})
    d = r.json()["data"]
    assert "summary" in d and "submittable" in d
    assert d["suggestion_id"] > 0
    # R5 对入库单必须跳过
    assert any(x["rule"] == "R5" and x["level"] == "SKIP" for x in d["results"])


def test_校验非法单据类型报错(client, ah):
    r = _post(client, "/api/v1/ai/checks/BOGUS/1", ah, {})
    assert r.json()["code"] == "WMS-4001"


def test_反馈与采纳率(seeded, client, kh, wh1_id):
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.domain.models import Product

    with SessionLocal() as s:
        pid = s.execute(select(Product.id).where(Product.code == "A3288")).scalar_one()

    sid = None
    for _ in range(2):
        r = _post(client, "/api/v1/ai/locations/recommend", kh,
                  {"sku_type": "PRODUCT", "sku_id": pid, "warehouse_id": wh1_id,
                   "qty": 5, "pallet_count": 1})
        sid = r.json()["data"]["suggestion_id"]

    assert _post(client, "/api/v1/ai/feedback", kh,
                 {"suggestion_id": sid, "action": "ACCEPT"}).json()["code"] == "0"
    # 拒绝必须给原因
    r = _post(client, "/api/v1/ai/feedback", kh,
              {"suggestion_id": sid, "action": "REJECT"})
    assert r.json()["code"] == "WMS-4001"
    r = _post(client, "/api/v1/ai/feedback", kh,
              {"suggestion_id": sid, "action": "REJECT", "reason": "不合适"})
    assert r.json()["code"] == "0"

    m = client.get("/api/v1/ai/metrics", headers=kh).json()["data"]
    loc = next((a for a in m["adoption"] if a["type"] == "LOCATION"), None)
    assert loc is not None and loc["accept"] >= 1 and loc["reject"] >= 1
    assert loc["rate"] is not None


def test_建议回放(seeded, client, kh, wh1_id):
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.domain.models import Product

    with SessionLocal() as s:
        pid = s.execute(select(Product.id).where(Product.code == "A3288")).scalar_one()
    sid = _post(client, "/api/v1/ai/locations/recommend", kh,
                {"sku_type": "PRODUCT", "sku_id": pid, "warehouse_id": wh1_id,
                 "qty": 1, "pallet_count": 1}).json()["data"]["suggestion_id"]
    r = client.get(f"/api/v1/ai/suggestions/{sid}", headers=kh).json()["data"]
    assert r["type"] == "LOCATION" and r["trace_id"]


def test_AI开关关闭时降级(seeded, client, ah, kh, wh1_id):
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.domain.models import Product

    with SessionLocal() as s:
        pid = s.execute(select(Product.id).where(Product.code == "A3288")).scalar_one()
    client.put("/api/v1/sys-configs", headers={**ah, "X-Client-Op-Id": str(uuid.uuid4())},
               json={"cfg_key": "ai_enabled", "cfg_value": "false", "value_type": "BOOL"})
    d = _post(client, "/api/v1/ai/locations/recommend", kh,
              {"sku_type": "PRODUCT", "sku_id": pid, "warehouse_id": wh1_id,
               "qty": 1, "pallet_count": 1}).json()["data"]
    assert d["degraded"] is True and d["primary"] is None


def test_未登录不能调AI接口(client):
    assert client.get("/api/v1/ai/metrics").status_code == 401


# ---------------------------------------------------------------- 提交前阻断（BR-017）
def test_出库可用库存不足时提交被阻断(seeded, client, kh, wh1_id, wh1_location_id):
    """R5 判 BLOCK，submit 必须拒绝并回传阻断规则。"""
    from sqlalchemy import select

    from app.ai import check_engine
    from app.core.db import SessionLocal
    from app.domain.models import Material, OutboundItem, OutboundOrder

    with SessionLocal() as s:
        mat = s.execute(select(Material.id).where(
            Material.code == "DSP-AMOLED-67-FULL")).scalar_one()
        o = OutboundOrder(no="SO-BLK-001", type="SALES", status="PENDING",
                          plan_qty=50, actual_qty=50, creator_id=1)
        s.add(o)
        s.flush()
        for _ in range(50):
            s.add(OutboundItem(order_id=o.id, sku_id=mat,
                               location_id=wh1_location_id, status="PICKED"))
        s.commit()
        oid = o.id

    r = _post(client, f"/api/v1/outbound-orders/{oid}/submit", kh, {})
    assert r.json()["code"] == "WMS-4221"
    assert "R5" in r.json()["data"]["blocking_rules"]

    # 直接调校验接口也应给出 submittable=false
    chk = _post(client, f"/api/v1/ai/checks/OUTBOUND/{oid}", kh, {}).json()["data"]
    assert chk["submittable"] is False
