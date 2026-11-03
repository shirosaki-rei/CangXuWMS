"""盘点、移位、供应商接口（接口 13–17、21、30–33、47）。"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.core.deps import CurrentUser, DbDep, StocktakeUser, SupplierAdmin
from app.core.errors import BizError, Codes, ok, page
from app.domain.models import Supplier
from app.schemas.stocktake import (
    CountReq,
    MoveCreateReq,
    MoveListQuery,
    StocktakeCreateReq,
    StocktakeListQuery,
    StocktakeSubmitReq,
    SupplierListQuery,
    SupplierUpdateReq,
)
from app.service import move_service, stocktake_service

router = APIRouter(tags=["库内作业"])


# ---------------------------------------------------------------- 盘点
@router.get("/stocktakes", summary="盘点单列表（接口 13 / P15）")
def list_stocktakes(request: Request, db: DbDep, _user: CurrentUser,
                    q: StocktakeListQuery = Depends()) -> dict:
    items, total = stocktake_service.list_stocktakes(db, q=q)
    return page(items, total, q.page, q.page_size, trace_id=request.state.trace_id)


@router.post("/stocktakes", summary="创建盘点单（接口 32，主管及以上）")
def create_stocktake(request: Request, db: DbDep, body: StocktakeCreateReq,
                     user: StocktakeUser) -> dict:
    return ok(stocktake_service.create(db, body, user.id), trace_id=request.state.trace_id)


@router.get("/stocktakes/{sid}", summary="盘点单详情（接口 14 / P16）")
def get_stocktake(request: Request, db: DbDep, sid: int, _user: CurrentUser) -> dict:
    return ok(stocktake_service.get_stocktake(db, sid), trace_id=request.state.trace_id)


@router.get("/stocktakes/{sid}/items", summary="盘点明细（接口 15，盲盘隐藏账面）")
def list_items(request: Request, db: DbDep, sid: int, user: CurrentUser) -> dict:
    # 盲盘对仓管员隐藏账面；主管与管理员可见（PRD 6.6.3）
    blind = user.role == "KEEPER"
    return ok(stocktake_service.list_items(db, sid, blind=blind),
              trace_id=request.state.trace_id)


@router.post("/stocktakes/{sid}/count", summary="提交实盘数（接口 30 / APP A09）")
def count(request: Request, db: DbDep, sid: int, body: CountReq,
          user: CurrentUser) -> dict:
    return ok(stocktake_service.count(db, sid, body, user.id),
              trace_id=request.state.trace_id)


@router.post("/stocktakes/{sid}/submit", summary="提交盘点（接口 31，生成盈亏单据）")
def submit(request: Request, db: DbDep, sid: int, body: StocktakeSubmitReq,
           user: StocktakeUser) -> dict:
    return ok(stocktake_service.submit(db, sid, body, user.id),
              trace_id=request.state.trace_id)


# ---------------------------------------------------------------- 移位
@router.get("/move-orders", summary="移位单列表（接口 16 / P17）")
def list_moves(request: Request, db: DbDep, _user: CurrentUser,
               q: MoveListQuery = Depends()) -> dict:
    items, total = move_service.list_moves(db, q=q)
    return page(items, total, q.page, q.page_size, trace_id=request.state.trace_id)


@router.get("/move-orders/{mid}", summary="移位单详情（接口 17）")
def get_move(request: Request, db: DbDep, mid: int, _user: CurrentUser) -> dict:
    return ok(move_service.get_move(db, mid), trace_id=request.state.trace_id)


@router.post("/move-orders", summary="发起移位（接口 33 / APP A09）")
def create_move(request: Request, db: DbDep, body: MoveCreateReq,
                user: CurrentUser) -> dict:
    return ok(move_service.create(db, body, user.id), trace_id=request.state.trace_id)


# ---------------------------------------------------------------- 供应商
@router.get("/suppliers", summary="供应商档案（接口 21）")
def list_suppliers(request: Request, db: DbDep, _user: CurrentUser,
                   q: SupplierListQuery = Depends()) -> dict:
    stmt = select(Supplier)
    if q.code:
        stmt = stmt.where(Supplier.code.like(f"%{q.code}%"))
    if q.name:
        stmt = stmt.where(Supplier.name.like(f"%{q.name}%"))
    if q.status:
        stmt = stmt.where(Supplier.status == q.status)
    rows = db.execute(stmt.order_by(Supplier.id)).scalars().all()
    return ok(
        [
            {
                "id": s.id,
                "code": s.code,
                "name": s.name,
                # BR-023：null 表示用全局默认
                "over_receive": float(s.over_receive) if s.over_receive is not None else None,
                "contact": s.contact,
                "status": s.status,
            }
            for s in rows
        ],
        trace_id=request.state.trace_id,
    )


@router.put("/suppliers/{sid}", summary="编辑供应商档案（接口 47，超收阈值覆盖 BR-023）")
def update_supplier(request: Request, db: DbDep, sid: int, body: SupplierUpdateReq,
                    user: SupplierAdmin) -> dict:
    s = db.get(Supplier, sid)
    if s is None:
        raise BizError(Codes.BAD_REQUEST, "供应商不存在")
    if body.name is not None:
        s.name = body.name
    if body.contact is not None:
        s.contact = body.contact
    if body.status is not None:
        s.status = body.status
    # 显式传 null 表示清除覆盖值，回落到全局默认
    if "over_receive" in body.model_fields_set:
        s.over_receive = Decimal(str(body.over_receive)) if body.over_receive is not None else None
    db.commit()
    return ok({"id": s.id, "over_receive": float(s.over_receive) if s.over_receive is not None else None},
              trace_id=request.state.trace_id)
