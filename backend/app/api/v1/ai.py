"""AI 能力接口（接口 52/53/54/56/57）。问数（55）在二期，本批不实现。

AI 路由只拿得到只读 session 取业务数据；写建议/反馈用写 session，
因为那是「记录 AI 说过什么」，不是改库存。
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai import service as ai
from app.core.deps import CurrentUser, DbDep, ReadOnlyDep, WarehouseScope
from app.core.errors import Codes, ok
from app.domain.models import AiSuggestion

router = APIRouter(prefix="/ai", tags=["AI 建议层"])


class RecommendReq(BaseModel):
    sku_type: str = Field(..., pattern=r"^(PRODUCT|MATERIAL)$")
    sku_id: int
    warehouse_id: int
    qty: int = Field(1, gt=0)
    pallet_count: int = Field(1, ge=0)
    order_id: int | None = None


class PickPoint(BaseModel):
    location_code: str
    qty: int = 1
    x: float | None = None
    y: float | None = None


class OptimizeReq(BaseModel):
    order_id: int | None = None
    order_type: str = Field("SALES", pattern=r"^(SALES|PICK|LOSS)$")
    points: list[PickPoint] | None = None


class QueryReq(BaseModel):
    question: str = Field(..., min_length=2, max_length=255)


class FeedbackReq(BaseModel):
    suggestion_id: int
    action: str = Field(..., pattern=r"^(ACCEPT|REJECT|REVOKE)$")
    reason: str | None = Field(None, max_length=64)


@router.post("/locations/recommend", summary="库位推荐（接口 52 / X02）")
def recommend(request: Request, db: DbDep, ro: ReadOnlyDep, body: RecommendReq,
              user: CurrentUser) -> dict:
    result = ai.recommend_locations(
        ro, sku_type=body.sku_type, sku_id=body.sku_id, warehouse_id=body.warehouse_id,
        qty=body.qty, pallet_count=body.pallet_count,
    )
    # 建议要落库，否则 X05 的采纳率统计不到（接口 3.4 注）
    sid = ai.save_suggestion(
        db, trace_id=result["trace_id"], kind="LOCATION", target_id=body.order_id or body.sku_id,
        payload=result,
        score=(result.get("primary") or {}).get("score"),
        reasons=(result.get("primary") or {}).get("reasons"),
    )
    result["suggestion_id"] = sid
    return ok(result, trace_id=request.state.trace_id)


@router.post("/picking/optimize", summary="拣货路径优化（接口 53 / X03）")
def optimize(request: Request, db: DbDep, ro: ReadOnlyDep, body: OptimizeReq,
             user: CurrentUser) -> dict:
    pts = [p.model_dump() for p in body.points] if body.points else None
    if not pts and body.order_id is None:
        from app.core.errors import BizError

        raise BizError(Codes.BAD_REQUEST, "要么传 points，要么传 order_id")
    result = ai.optimize_path(ro, order_id=body.order_id or 0,
                              order_type=body.order_type, points=pts)
    sid = ai.save_suggestion(
        db, trace_id=result["trace_id"], kind="PATH", target_id=body.order_id or 0,
        payload=result, score=result.get("saved_pct"),
    )
    result["suggestion_id"] = sid
    return ok(result, trace_id=request.state.trace_id)


@router.post("/checks/{order_type}/{order_id}", summary="提交前校验（接口 54 / X04）")
def checks(request: Request, db: DbDep, ro: ReadOnlyDep, order_type: str, order_id: int,
           user: CurrentUser) -> dict:
    ot = order_type.upper()
    if ot not in ("INBOUND", "OUTBOUND", "STOCKTAKE"):
        from app.core.errors import BizError

        raise BizError(Codes.BAD_REQUEST, "order_type 只能是 INBOUND / OUTBOUND / STOCKTAKE")
    result = ai.run_checks(ro, ot, order_id)
    result["suggestion_id"] = ai.persist_check_suggestion(db, ot, order_id, result)
    return ok(result, trace_id=request.state.trace_id)


@router.post("/feedback", summary="建议反馈（接口 57 / X05 采纳率唯一来源）")
def feedback(request: Request, db: DbDep, body: FeedbackReq, user: CurrentUser) -> dict:
    return ok(ai.record_feedback(db, suggestion_id=body.suggestion_id, action=body.action,
                                 reason=body.reason, operator_id=user.id),
              trace_id=request.state.trace_id)


@router.get("/metrics", summary="AI 效果看板（接口 56 / X05）")
def metrics(request: Request, db: DbDep, user: CurrentUser,
            days: int = Query(30, ge=1, le=365)) -> dict:
    return ok(ai.metrics(db, days=days), trace_id=request.state.trace_id)


@router.get("/suggestions/{sid}", summary="取一条建议记录（回放用）")
def get_suggestion(request: Request, db: DbDep, sid: int, user: CurrentUser) -> dict:
    row = db.execute(select(AiSuggestion).where(AiSuggestion.id == sid)).scalar_one_or_none()
    if row is None:
        from app.core.errors import BizError

        raise BizError(Codes.BAD_REQUEST, "建议不存在")
    return ok({"id": row.id, "trace_id": row.trace_id, "type": row.type,
               "target_id": row.target_id, "payload": row.payload,
               "score": float(row.score) if row.score is not None else None,
               "reasons": row.reasons}, trace_id=request.state.trace_id)


@router.post("/query", summary="自然语言问数（接口 55 / X01，只读）")
def query(request: Request, db: DbDep, ro: ReadOnlyDep, scope: WarehouseScope,
          body: QueryReq, user: CurrentUser) -> dict:
    from app.ai.nl_query import service as nq

    # 数据权限：仓管员/检验员只查可见仓库，主管/管理员不限（AC-AI-12）
    return ok(nq.ask(ro, db, question=body.question, user_id=user.id, warehouse_ids=scope),
              trace_id=request.state.trace_id)
