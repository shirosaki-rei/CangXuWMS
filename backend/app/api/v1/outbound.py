"""出库单接口（接口 9/10/28/29/38，页面 P10–P13）。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from app.core.deps import CurrentUser, DbDep, InboundVoidUser, WarehouseScope
from app.core.errors import BizError, Codes, ok, page
from app.schemas.outbound import (
    OutboundListQuery,
    OutboundSubmitReq,
    OutboundVoidReq,
    PickReq,
)
from app.service import outbound_service as svc

router = APIRouter(prefix="/outbound-orders", tags=["出库管理"])


@router.get("", summary="出库单列表（接口 9 / P10–P12）")
def list_orders(request: Request, db: DbDep, scope: WarehouseScope, _user: CurrentUser,
                q: OutboundListQuery = Depends()) -> dict:
    items, total = svc.list_orders(db, scope=scope, q=q)
    return page(items, total, q.page, q.page_size, trace_id=request.state.trace_id)


@router.get("/status-counts", summary="三类 Tab 角标")
def status_counts(request: Request, db: DbDep, _user: CurrentUser) -> dict:
    return ok(svc.status_counts(db), trace_id=request.state.trace_id)


@router.get("/{order_id}", summary="出库单详情（接口 10 / P13）")
def get_order(request: Request, db: DbDep, order_id: int, _user: CurrentUser) -> dict:
    return ok(svc.get_order(db, order_id), trace_id=request.state.trace_id)


@router.get("/{order_id}/fifo", summary="FIFO 拣货库位推荐（BR-003）")
def fifo(request: Request, db: DbDep, scope: WarehouseScope, order_id: int,
         _user: CurrentUser) -> dict:
    """按入库完成时间升序排出该单 SKU 的可用库位序列。"""
    o = svc.get_order(db, order_id)
    sku_id = o["items"][0]["sku_id"] if o["items"] else None
    if sku_id is None:
        raise BizError(Codes.BIZ_RULE, "出库单没有明细，无法推荐库位")
    return ok(
        svc.recommend(db, svc.sku_type_of(o["type"]), sku_id, o["plan_qty"], scope=scope),
        trace_id=request.state.trace_id,
    )


@router.post("/{order_id}/pick", summary="扫码拣货（接口 28 / A07/A08）")
def pick(request: Request, db: DbDep, order_id: int, body: PickReq,
          user: CurrentUser) -> dict:
    return ok(svc.pick(db, order_id, body, user.id), trace_id=request.state.trace_id)


@router.post("/{order_id}/submit", summary="提交出库（接口 29 / P13 → X04）")
def submit(request: Request, db: DbDep, order_id: int, body: OutboundSubmitReq,
           user: CurrentUser, bg: BackgroundTasks) -> dict:
    result = svc.submit(db, order_id, body, user.id)
    from app.service.integration_service import outbound_payload, send_callback
    from app.domain.models import OutboundOrder

    o = db.get(OutboundOrder, order_id)
    if o is not None:
        bg.add_task(send_callback, db, "MES", outbound_payload(o))
    return ok(result, trace_id=request.state.trace_id)


@router.post("/{order_id}/void", summary="作出库单（接口 38，主管及以上）")
def void(request: Request, db: DbDep, order_id: int, body: OutboundVoidReq,
         user: InboundVoidUser) -> dict:
    return ok(svc.void(db, order_id, body, user.id), trace_id=request.state.trace_id)
