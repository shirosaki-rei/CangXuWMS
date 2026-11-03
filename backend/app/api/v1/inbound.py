"""入库单接口（接口 7/8/26/27/37，页面 P05–P09）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.core.deps import CurrentUser, DbDep, InboundVoidUser
from app.core.errors import ok, page
from app.schemas.inbound import (
    InboundListQuery,
    ScanReq,
    SubmitReq,
    VoidReq,
)
from app.service import inbound_service as svc

router = APIRouter(prefix="/inbound-orders", tags=["入库管理"])


@router.get("", summary="入库单列表（接口 7 / P05–P08）")
def list_orders(request: Request, db: DbDep, _user: CurrentUser,
                q: InboundListQuery = Depends()) -> dict:
    items, total = svc.list_orders(db, scope=None, q=q)
    return page(items, total, q.page, q.page_size, trace_id=request.state.trace_id)


@router.get("/status-counts", summary="四类 Tab 角标")
def status_counts(request: Request, db: DbDep, _user: CurrentUser) -> dict:
    return ok(svc.status_counts(db), trace_id=request.state.trace_id)


@router.get("/{order_id}", summary="入库单详情（接口 8 / P09）")
def get_order(request: Request, db: DbDep, order_id: int, _user: CurrentUser) -> dict:
    return ok(svc.get_order(db, order_id), trace_id=request.state.trace_id)


@router.post("/{order_id}/scan", summary="扫码收货（接口 26 / A02–A04）")
def scan(request: Request, db: DbDep, order_id: int, body: ScanReq,
         user: CurrentUser) -> dict:
    return ok(svc.scan(db, order_id, body, user.id), trace_id=request.state.trace_id)


@router.post("/{order_id}/submit", summary="提交入库（接口 27 / P09 → X04）")
def submit(request: Request, db: DbDep, order_id: int, body: SubmitReq,
           user: CurrentUser) -> dict:
    return ok(svc.submit(db, order_id, body, user.id), trace_id=request.state.trace_id)


@router.post("/{order_id}/void", summary="作废入库单（接口 37，主管及以上）")
def void(request: Request, db: DbDep, order_id: int, body: VoidReq,
         user: InboundVoidUser) -> dict:
    return ok(svc.void(db, order_id, body, user.id), trace_id=request.state.trace_id)
