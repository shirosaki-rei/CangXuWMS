"""库存与流水查询接口（接口 4/5/6/25，页面 P01–P04）。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.core.deps import DbDep, InventoryViewer, WarehouseScope
from app.core.errors import BizError, Codes, ok, page
from app.schemas.inventory import ExportQuery, InventoryQuery, TxnQuery
from app.service import inventory_service as svc

router = APIRouter(tags=["库存与流水查询"])

# 导出行数上限（PRD 6.3.1）
EXPORT_MAX_ROWS = 50_000


@router.get("/inventory/products", summary="成品库存明细（接口 4 / P01）")
def products(request: Request, db: DbDep, scope: WarehouseScope, _user: InventoryViewer,
             q: InventoryQuery = Depends()) -> dict:
    items, total = svc.list_products(db, scope=scope, q=q)
    return page(items, total, q.page, q.page_size, trace_id=request.state.trace_id)


@router.get("/inventory/materials", summary="物料库存明细（接口 5 / P02）")
def materials(request: Request, db: DbDep, scope: WarehouseScope, _user: InventoryViewer,
              q: InventoryQuery = Depends()) -> dict:
    items, total = svc.list_materials(db, scope=scope, q=q)
    return page(items, total, q.page, q.page_size, trace_id=request.state.trace_id)


@router.get("/txn", summary="出入库流水（接口 6 / P03/P04）")
def txn(request: Request, db: DbDep, scope: WarehouseScope, _user: InventoryViewer,
        q: TxnQuery = Depends()) -> dict:
    items, total = svc.list_txn(db, scope=scope, q=q)
    return page(items, total, q.page, q.page_size, trace_id=request.state.trace_id)


@router.get("/txn/summary", summary="单 SKU 库存汇总（行下钻用）")
def txn_summary(request: Request, db: DbDep, scope: WarehouseScope, _user: InventoryViewer,
                sku_type: str = Query(..., pattern=r"^(PRODUCT|MATERIAL)$"),
                sku_id: int = Query(...)) -> dict:
    data = svc.sku_summary(db, sku_type, sku_id)
    data["locations"] = svc.location_breakdown(db, sku_type, sku_id)
    return ok(data, trace_id=request.state.trace_id)


@router.get("/export/{biz}", summary="异步导出 CSV（接口 25）")
def export(request: Request, db: DbDep, scope: WarehouseScope, _user: InventoryViewer,
           biz: str, q: ExportQuery = Depends()) -> dict:
    """数据量小时同步返回 CSV；超过上限才需要异步（B06 接 APScheduler）。

    ponytail: 直接同步流式输出，没做任务号 + 轮询那套。日均 800–2000 单的量级下
    5 万行 CSV 也就几 MB，一个请求能扛住；真出现超时再拆异步。
    """
    rows, cols = svc.export_rows(db, scope=scope, q=q)
    if len(rows) > EXPORT_MAX_ROWS:
        raise BizError(
            Codes.BIZ_RULE,
            f"导出超过 {EXPORT_MAX_ROWS} 行上限，请缩小时间范围",
            data={"limit": EXPORT_MAX_ROWS},
        )

    buf = io.StringIO()
    buf.write("﻿")  # BOM，Excel 打开中文不乱码
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})

    filename = f"{biz}_{request.state.trace_id[:8]}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
