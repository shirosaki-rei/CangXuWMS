"""来料检验接口（接口 11/12/34/35/36，页面 P14/A05）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.deps import CurrentUser, DbDep, InspectorUser
from app.core.errors import ok, page
from app.schemas.inbound import (
    GenInboundReq,
    InspectionJudgeReq,
    InspectionListQuery,
    InspectionScanReq,
)
from app.service import inspection_service as svc

router = APIRouter(prefix="/inspections", tags=["来料检验"])

@router.get("", summary="检验单列表（接口 11 / P14）")
def list_inspections(request: Request, db: DbDep, _user: CurrentUser,
                     q: InspectionListQuery = Depends()) -> dict:
    items, total = svc.list_inspections(db, q=q)
    return page(items, total, q.page, q.page_size, trace_id=request.state.trace_id)


@router.get("/{inspection_id}", summary="检验单详情（接口 12 / P14 详情）")
def get_inspection(request: Request, db: DbDep, inspection_id: int,
                   _user: CurrentUser) -> dict:
    return ok(svc.get_inspection(db, inspection_id), trace_id=request.state.trace_id)


@router.post("/{inspection_id}/scan", summary="来料检验扫码（接口 34 / A05）")
def scan(request: Request, db: DbDep, inspection_id: int, body: InspectionScanReq,
         user: InspectorUser) -> dict:
    return ok(svc.scan(db, inspection_id, body, user.id), trace_id=request.state.trace_id)


@router.post("/{inspection_id}/judge", summary="检验判定（接口 35 / P14）")
def judge(request: Request, db: DbDep, inspection_id: int, body: InspectionJudgeReq,
          user: InspectorUser) -> dict:
    return ok(svc.judge(db, inspection_id, body, user.id), trace_id=request.state.trace_id)


@router.post("/{inspection_id}/gen-inbound", summary="生成采购入库单（接口 36）")
def gen_inbound(request: Request, db: DbDep, inspection_id: int,
                body: GenInboundReq | None = None, user: InspectorUser = None) -> dict:
    """body 可省略：全字段可选时也要允许空 body，否则对端调用直接被 4001 挡掉。"""
    return ok(svc.gen_inbound(db, inspection_id, body or GenInboundReq(), user.id),
              trace_id=request.state.trace_id)
