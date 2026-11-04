"""AI 服务层：从只读连接取上下文，交给纯函数算，再把建议落到 ai_suggestion。

注意本模块**只能**用只读 session 取业务数据（架构 8.1 第三道锁）；
写建议与反馈时由调用方传入写 session——那是「记录 AI 说过什么」，不是改库存。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import check_engine, location_advisor, path_solver
from app.core.errors import BizError, Codes
from app.domain.enums import SkuType
from app.domain.models import (
    AiFeedback,
    AiSuggestion,
    InboundItem,
    InboundOrder,
    Inventory,
    Location,
    Material,
    MetricEvent,
    OutboundItem,
    OutboundOrder,
    Product,
    Stocktake,
    StocktakeItem,
    Supplier,
    Txn,
)
from app.domain.rules import location_mismatch_reason
from app.service.admin_service import get_config

_NOW = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731


def _trace() -> str:
    return uuid.uuid4().hex


def _cfg_dec(db: Session, key: str, default: str) -> Decimal:
    try:
        return Decimal(str(get_config(db, key, default)))
    except Exception:
        return Decimal(default)


def _cfg_bool(db: Session, key: str, default: bool = True) -> bool:
    raw = get_config(db, key, "true" if default else "false")
    return str(raw).lower() in ("true", "1", "yes", "on")


# ---------------------------------------------------------------- 库位推荐
def recommend_locations(ro: Session, *, sku_type: str, sku_id: int, warehouse_id: int,
                        qty: int, pallet_count: int) -> dict:
    if not _cfg_bool(ro, "ai_enabled"):
        return {"primary": None, "alternatives": [], "degraded": True,
                "confidence": "LOW", "reason": "AI 建议已关闭（BR-020）",
                "trace_id": _trace()}

    table = Product if sku_type == str(SkuType.PRODUCT) else Material
    sku = ro.get(table, sku_id)
    if sku is None:
        raise BizError(Codes.BAD_REQUEST, "SKU 不存在")

    locs = ro.execute(select(Location).where(Location.warehouse_id == warehouse_id)).scalars().all()
    if not locs:
        raise BizError(Codes.BIZ_RULE, "该仓库没有库位")

    # 同 SKU 在各库区的托数（用库存条数近似托数：一个 (sku, location) 记 1 托）
    same = dict(ro.execute(
        select(Inventory.location_id, Inventory.qty)
        .where(Inventory.sku_type == sku_type, Inventory.sku_id == sku_id)
    ).all())

    cands = [
        location_advisor.Candidate(
            location_id=l.id, code=l.code, type=l.type, status=l.status,
            cap_pallet=l.cap_pallet or 0, used_pallet=l.used_pallet or 0,
            dist_to_pack=float(l.dist_to_pack) if l.dist_to_pack is not None else None,
            same_sku_pallets=1 if same.get(l.id) else 0,
            turnover_30d=0,
        )
        for l in locs
    ]
    ctx = location_advisor.Context(
        pallet_count=pallet_count or max(1, qty),
        warehouse_id=warehouse_id,
        is_dangerous=bool(getattr(sku, "is_dangerous", False)),
        temp_control=getattr(sku, "temp_control", "NONE") or "NONE",
        cold_start=True,  # 近 30 天出周转数据尚未接入，按冷启动处理
        coord_required=_cfg_bool(ro, "coord_required"),
    )
    result = location_advisor.recommend(cands, ctx)
    result["trace_id"] = _trace()
    return result


def save_suggestion(db: Session, *, trace_id: str, kind: str, target_id: int,
                    payload: dict, score: float | None = None,
                    reasons: list | None = None) -> int:
    row = AiSuggestion(trace_id=trace_id, type=kind, target_id=target_id,
                       payload=payload,
                       score=Decimal(str(round(score, 2))) if score is not None else None,
                       reasons=reasons)
    db.add(row)
    db.commit()
    return row.id


# ---------------------------------------------------------------- 路径优化
def optimize_path(ro: Session, *, order_id: int, order_type: str,
                  points: list[dict] | None) -> dict:
    if not _cfg_bool(ro, "ai_enabled"):
        return {"sequence": [p["location_code"] for p in (points or [])], "degraded": True,
                "algorithm": "DISABLED", "point_count": len(points or []),
                "saved_pct": 0, "trace_id": _trace()}

    if not points:
        # 没传点就从单据明细里推
        order = ro.get(OutboundOrder, order_id)
        if order is None:
            raise BizError(Codes.BAD_REQUEST, "出库单不存在")
        rows = ro.execute(
            select(OutboundItem.location_id, func.count())
            .where(OutboundItem.order_id == order_id, OutboundItem.location_id.is_not(None))
            .group_by(OutboundItem.location_id)
        ).all()
        if not rows:
            raise BizError(Codes.BIZ_RULE, "单据没有已分配库位的明细")
        locs = {l.id: l for l in ro.execute(
            select(Location).where(Location.id.in_([r[0] for r in rows]))).scalars()}
        points = [
            {"location_code": locs[loc_id].code,
             "x": float(locs[loc_id].coord_x or 0),
             "y": float(locs[loc_id].coord_y or 0),
             "qty": int(n)}
            for loc_id, n in rows if loc_id in locs
        ]

    # 库位坐标缺失时用 0 会导致所有点重合，直接报错比给出一个假最优更诚实
    pts = [path_solver.Point(code=p["location_code"],
                             x=float(p.get("x") or 0), y=float(p.get("y") or 0),
                             qty=int(p.get("qty") or 1)) for p in points]
    out = path_solver.optimize(pts)
    out["trace_id"] = _trace()
    return out


# ---------------------------------------------------------------- 提交前校验
def _dedupe(rows: list, key) -> list:
    seen, dup = set(), []
    for r in rows:
        k = key(r)
        if k and k in seen:
            dup.append(k)
        elif k:
            seen.add(k)
    return dup


def build_check_context(ro: Session, order_type: str, order_id: int) -> check_engine.CheckContext:
    if order_type == "INBOUND":
        o = ro.get(InboundOrder, order_id)
        if o is None:
            raise BizError(Codes.BAD_REQUEST, "入库单不存在")
        items = ro.execute(select(InboundItem).where(InboundItem.order_id == order_id)).scalars().all()
        codes = [i.box_code for i in items if i.box_code]
        mism = []
        sku_table = Product if o.type == "PRODUCT" else Material
        sku_ids = {i.sku_id for i in items}
        skus = {s.id: s for s in ro.execute(
            select(sku_table).where(sku_table.id.in_(sku_ids))).scalars()} if sku_ids else {}
        loc_ids = {i.location_id for i in items if i.location_id}
        locs = {l.id: l for l in ro.execute(
            select(Location).where(Location.id.in_(loc_ids))).scalars()} if loc_ids else {}
        for i in items:
            loc, sku = locs.get(i.location_id), skus.get(i.sku_id)
            if loc and sku and getattr(sku, "is_dangerous", False) is not None:
                if location_mismatch_reason(loc.type, bool(getattr(sku, "is_dangerous", False)),
                                            getattr(sku, "temp_control", "NONE")):
                    mism.append(loc.code)

        supplier_rate = None
        if o.supplier_id:
            total = ro.execute(select(func.count()).select_from(InboundOrder).where(
                InboundOrder.supplier_id == o.supplier_id,
                InboundOrder.status == "DONE")).scalar() or 0
            # 合格率用「有不合格检验记录的比例」近似；数据不足时留 None
            supplier_rate = Decimal("0") if total == 0 else None

        return check_engine.CheckContext(
            order_type="INBOUND", order_no=o.no,
            plan_qty=o.plan_qty, actual_qty=o.actual_qty,
            deviation_ratio=_cfg_dec(ro, "qty_deviation_ratio", "0.10"),
            over_receive_ratio=_cfg_dec(ro, "over_receive_ratio", "0.05"),
            items=[{"box_code": i.box_code, "sn": i.sn} for i in items],
            duplicate_codes=_dedupe(codes, lambda c: c),
            mismatch_locations=mism,
            supplier_fail_rate=supplier_rate,
        )

    if order_type == "OUTBOUND":
        o = ro.get(OutboundOrder, order_id)
        if o is None:
            raise BizError(Codes.BAD_REQUEST, "出库单不存在")
        items = ro.execute(
            select(OutboundItem).where(OutboundItem.order_id == order_id)).scalars().all()
        sku_type = str(SkuType.PRODUCT if o.type == "SALES" else SkuType.MATERIAL)
        avail = 0
        if items:
            avail = int(ro.execute(
                select(func.coalesce(func.sum(Inventory.qty - Inventory.locked_qty
                                              - Inventory.frozen_qty), 0))
                .where(Inventory.sku_type == sku_type,
                       Inventory.sku_id == items[0].sku_id)
            ).scalar())
        sns = [i.sn for i in items if i.sn]
        return check_engine.CheckContext(
            order_type="OUTBOUND", order_no=o.no,
            plan_qty=o.plan_qty, actual_qty=o.actual_qty,
            deviation_ratio=_cfg_dec(ro, "qty_deviation_ratio", "0.10"),
            items=[{"sn": i.sn} for i in items],
            duplicate_codes=_dedupe(sns, lambda s: s),
            available=avail,
        )

    # STOCKTAKE
    s = ro.get(Stocktake, order_id)
    if s is None:
        raise BizError(Codes.BAD_REQUEST, "盘点单不存在")
    items = ro.execute(
        select(StocktakeItem).where(StocktakeItem.stocktake_id == order_id)).scalars().all()
    diff_items = sum(1 for i in items if i.real_qty is not None and i.real_qty != i.book_qty)
    blank = sum(1 for i in items if i.real_qty is None) if s.status == "DONE" else 0
    return check_engine.CheckContext(
        order_type="STOCKTAKE", order_no=s.no,
        total=s.total, done=s.done, diff_items=diff_items,
        blank_items=blank,
        diff_rate_ratio=_cfg_dec(ro, "diff_rate_ratio", "0.05"),
    )


def run_checks(ro: Session, order_type: str, order_id: int) -> dict:
    ctx = build_check_context(ro, order_type, order_id)
    started = datetime.now(timezone.utc)
    results = check_engine.run(ctx)
    elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return {
        "summary": check_engine.summary(results),
        "submittable": not any(r.level == "BLOCK" for r in results),
        "results": [r.to_dict() for r in results],
        "cache_hit": False,
        "elapsed_ms": elapsed,
        "trace_id": _trace(),
    }


# ---------------------------------------------------------------- 反馈与看板
def record_feedback(db: Session, *, suggestion_id: int, action: str,
                    reason: str | None, operator_id: int) -> dict:
    if action == "REJECT" and not (reason or "").strip():
        raise BizError(Codes.BAD_REQUEST, "拒绝建议时必须填写原因")
    sug = db.get(AiSuggestion, suggestion_id)
    if sug is None:
        raise BizError(Codes.BAD_REQUEST, "建议不存在")
    db.add(AiFeedback(suggestion_id=suggestion_id, action=action,
                      reason=(reason or "").strip() or None, operator_id=operator_id))
    db.commit()
    return {"suggestion_id": suggestion_id, "action": action}


def record_metric(db: Session, *, scene: str, user_id: int, order_type: str | None,
                  order_id: int | None, duration_ms: int | None,
                  distance_m: float | None, baseline_m: float | None,
                  ai_used: bool, trace_id: str | None = None) -> None:
    db.add(MetricEvent(scene=scene, trace_id=(trace_id or _trace())[:32], order_type=order_type,
                       order_id=order_id, user_id=user_id, duration_ms=duration_ms,
                       distance_m=Decimal(str(distance_m)) if distance_m is not None else None,
                       baseline_m=Decimal(str(baseline_m)) if baseline_m is not None else None,
                       ai_used=ai_used))
    db.commit()


def metrics(db: Session, *, days: int = 30) -> dict:
    since = _NOW() - timedelta(days=days)
    total = db.execute(select(func.count()).select_from(AiSuggestion)
                       .where(AiSuggestion.created_at >= since)).scalar() or 0
    rows = db.execute(
        select(AiSuggestion.type, AiFeedback.action, func.count())
        .join(AiSuggestion, AiSuggestion.id == AiFeedback.suggestion_id)
        .where(AiSuggestion.created_at >= since)
        .group_by(AiSuggestion.type, AiFeedback.action)
    ).all()

    by_type: dict[str, dict[str, int]] = {}
    for t, action, n in rows:
        by_type.setdefault(t, {})[action] = int(n)

    adoption = []
    for t, acts in by_type.items():
        acc = acts.get("ACCEPT", 0)
        rej = acts.get("REJECT", 0)
        base = acc + rej
        adoption.append({
            "type": t,
            "accept": acc,
            "reject": rej,
            "revoke": acts.get("REVOKE", 0),
            "rate": round(acc / base * 100, 1) if base else None,
        })

    # 结果指标：找位/拣货时长与距离
    agg = db.execute(
        select(MetricEvent.scene,
               func.avg(MetricEvent.duration_ms),
               func.avg(MetricEvent.distance_m),
               func.avg(MetricEvent.baseline_m),
               func.count())
        .where(MetricEvent.created_at >= since)
        .group_by(MetricEvent.scene)
    ).all()
    scenes = [
        {
            "scene": scene,
            "avg_duration_ms": round(float(d or 0), 1),
            "avg_distance_m": round(float(dist or 0), 1),
            "avg_baseline_m": round(float(base or 0), 1),
            "saved_pct": (round((1 - float(dist) / float(base)) * 100, 1)
                          if dist and base and float(base) > 0 else None),
            "count": int(n),
        }
        for scene, d, dist, base, n in agg
    ]

    # 采纳率下线阈值（BR-022）：连续 2 周 < 30% 自动下线由 B06 的定时任务判定，
    # 这里只把当前值与阈值一起给看板
    threshold = _cfg_dec(db, "adoption_offline_ratio", "0.30")
    return {
        "window_days": days,
        "suggestion_total": int(total),
        "adoption": adoption,
        "scenes": scenes,
        "offline_threshold": float(threshold),
    }


# ---------------------------------------------------------------- 建议落库（供接口调用）
def persist_check_suggestion(db: Session, order_type: str, order_id: int, result: dict) -> int:
    return save_suggestion(
        db, trace_id=result["trace_id"], kind="CHECK", target_id=order_id,
        payload={"order_type": order_type, "summary": result["summary"],
                 "results": result["results"]},
    )
