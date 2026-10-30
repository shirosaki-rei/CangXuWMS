"""基础资料接口（接口文档 18–20、39–46；页面 P18/P19/P20）。"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.core.deps import (
    BaseDataAdmin,
    BaseDataViewer,
    DbDep,
    WarehouseScope,
    enforce_warehouse,
)
from app.core.errors import ok, page
from app.schemas.basedata import (
    BarcodeIn,
    BarcodePrintIn,
    LocationIn,
    LocationStatusIn,
    WarehouseIn,
    WarehouseToggle,
)
from app.service import base_data_service as svc

router = APIRouter(prefix="/warehouses", tags=["基础资料-仓库 P18"])
loc_router = APIRouter(prefix="/locations", tags=["基础资料-库位 P19"])
bar_router = APIRouter(prefix="/barcodes", tags=["基础资料-条码 P20"])

# ---------------------------------------------------------------- 仓库
@router.get("", summary="仓库列表（接口 18）")
def list_warehouses(
    request: Request,
    db: DbDep,
    scope: WarehouseScope,
    _user: BaseDataViewer,
    name: str | None = Query(None),
    type: str | None = Query(None),
    status: str | None = Query(None),
) -> dict:
    return ok(svc.list_warehouses(db, name=name, wtype=type, status=status, scope=scope),
              trace_id=request.state.trace_id)


@router.post("", summary="新增仓库（接口 39）")
def create_warehouse(request: Request, db: DbDep, body: WarehouseIn,
                     _user: BaseDataAdmin) -> dict:
    return ok({"id": svc.create_warehouse(db, body)}, trace_id=request.state.trace_id)


@router.put("/{wid}", summary="编辑仓库（接口 40）")
def update_warehouse(request: Request, db: DbDep, wid: int, body: WarehouseIn,
                     _user: BaseDataAdmin) -> dict:
    svc.update_warehouse(db, wid, body)
    return ok({"ok": True}, trace_id=request.state.trace_id)


@router.post("/{wid}/toggle", summary="启用/停用仓库（接口 41，BR-014）")
def toggle_warehouse(request: Request, db: DbDep, wid: int, body: WarehouseToggle,
                     _user: BaseDataAdmin) -> dict:
    svc.toggle_warehouse(db, wid, str(body.status))
    return ok({"ok": True}, trace_id=request.state.trace_id)


@router.get("/{wid}/blockers", summary="停用阻塞项清单")
def warehouse_blockers(request: Request, db: DbDep, wid: int,
                       _user: BaseDataViewer) -> dict:
    return ok({"blockers": svc.location_blockers(db, wid)}, trace_id=request.state.trace_id)


# ---------------------------------------------------------------- 库位
@loc_router.get("", summary="库位列表（接口 19）")
def list_locations(
    request: Request,
    db: DbDep,
    scope: WarehouseScope,
    _user: BaseDataViewer,
    warehouse_id: int | None = Query(None),
    type: str | None = Query(None),
    status: str | None = Query(None),
    code: str | None = Query(None),
    page_no: int = Query(1, ge=1, alias="page"),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    # 数据权限：显式传了 warehouse_id 也要过一遍可见范围，不接受前端绕过（接口 1.4）
    enforce_warehouse(scope, warehouse_id)
    items = svc.list_locations(db, warehouse_id=warehouse_id, ltype=type, status=status,
                               code=code, scope=scope)
    start = (page_no - 1) * page_size
    return page(items[start:start + page_size], len(items), page_no, page_size,
                trace_id=request.state.trace_id)


@loc_router.post("", summary="新增库位（接口 42）")
def create_location(request: Request, db: DbDep, body: LocationIn,
                    _user: BaseDataAdmin) -> dict:
    return ok({"id": svc.create_location(db, body)}, trace_id=request.state.trace_id)


@loc_router.put("/{lid}", summary="编辑库位（接口 43，含坐标）")
def update_location(request: Request, db: DbDep, lid: int, body: LocationIn,
                    _user: BaseDataAdmin) -> dict:
    svc.update_location(db, lid, body)
    return ok({"ok": True}, trace_id=request.state.trace_id)


@loc_router.post("/{lid}/status", summary="设置库位状态（接口 44，BR-008）")
def set_location_status(request: Request, db: DbDep, lid: int, body: LocationStatusIn,
                        _user: BaseDataAdmin) -> dict:
    svc.set_location_status(db, lid, str(body.status))
    return ok({"ok": True}, trace_id=request.state.trace_id)


# ---------------------------------------------------------------- 条码
@bar_router.get("", summary="条码列表（接口 20）")
def list_barcodes(request: Request, db: DbDep, _user: BaseDataViewer,
                  type: str | None = Query(None), code: str | None = Query(None)) -> dict:
    return ok(svc.list_barcodes(db, btype=type, code=code), trace_id=request.state.trace_id)


@bar_router.post("", summary="生成条码（接口 45，BR-009 全局唯一）")
def create_barcode(request: Request, db: DbDep, body: BarcodeIn,
                   _user: BaseDataAdmin) -> dict:
    return ok({"id": svc.create_barcode(db, body)}, trace_id=request.state.trace_id)


@bar_router.post("/print", summary="批量打印（接口 46）")
def print_barcodes(request: Request, db: DbDep, body: BarcodePrintIn,
                   _user: BaseDataAdmin) -> dict:
    return ok(svc.print_barcodes(db, body.ids, body.spec, body.copies),
              trace_id=request.state.trace_id)
