"""集成接口（MES → WMS，接口 62）。签名校验见 core/integration_auth.py。

幂等键 = no + version（接口文档 4.1）：重复推送返回首次结果（WMS-4091），不产生重复单据。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.core.deps import DbDep
from app.core.errors import BizError, Codes, ok
from app.core.integration_auth import IntegrationClient
from app.domain.models import Inspection, InspectionItem, Material, Supplier
from app.schemas.integration import InspectionPushReq

router = APIRouter(prefix="/integration", tags=["集成接口（MES/ERP）"])


@router.post("/inspections", summary="MES 推送检验任务（接口 62）")
def push_inspection(request: Request, db: DbDep, body: InspectionPushReq,
                    client: IntegrationClient) -> dict:
    existing = db.execute(
        select(Inspection).where(Inspection.no == body.no)
    ).scalar_one_or_none()
    if existing is not None:
        # 同一 no 重复推送：原样返回首次结果，不新建单据
        return {
            "code": Codes.REPLAY,
            "message": "重复推送，已返回首次结果",
            "data": {"id": existing.id, "no": existing.no, "status": existing.status},
            "trace_id": request.state.trace_id,
        }

    supplier_id = _resolve_supplier(db, body.supplier_code)
    material_ids = [_resolve_material(db, i.material_code) for i in body.items]

    insp = Inspection(
        no=body.no,
        supplier_id=supplier_id,
        logistics_no=body.logistics_no,
        plate_no=body.plate_no,
        status="PENDING",
        plan_qty=sum(i.plan_qty for i in body.items),
        actual_qty=0,
        creator_id=0,  # 系统账号，无对应用户
    )
    db.add(insp)
    db.flush()
    for item, material_id in zip(body.items, material_ids):
        db.add(InspectionItem(inspection_id=insp.id, material_id=material_id,
                              plan_qty=item.plan_qty, actual_qty=0))
    db.commit()

    return ok({"id": insp.id, "no": insp.no, "status": insp.status},
              trace_id=request.state.trace_id)


def _resolve_supplier(db, code: str) -> int:
    sid = db.execute(select(Supplier.id).where(Supplier.code == code)).scalar_one_or_none()
    if sid is None:
        raise BizError(Codes.BAD_REQUEST, f"供应商编码 {code} 未维护")
    return sid


def _resolve_material(db, code: str) -> int:
    mid = db.execute(select(Material.id).where(Material.code == code)).scalar_one_or_none()
    if mid is None:
        raise BizError(Codes.BAD_REQUEST, f"物料编码 {code} 未维护")
    return mid
