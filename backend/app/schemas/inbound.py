"""入库单与来料检验的请求 schema（接口 7/8/11/12/26/27/34/35/36/37）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class InboundListQuery(BaseModel):
    type: str | None = Field(None, pattern=r"^(PRODUCT|PURCHASE|RETURN|GAIN)$")
    status: str | None = Field(None, pattern=r"^(PENDING|PARTIAL|DONE|VOID)$")
    no: str | None = None
    source_no: str | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class ScanReq(BaseModel):
    """扫码收货。location_id 是上架库位，SN 逐件入库时必填。"""

    box_code: str | None = Field(None, max_length=64)
    sn: str | None = Field(None, max_length=64)
    location_id: int | None = None
    qty: int = Field(1, gt=0)


class SubmitReq(BaseModel):
    """提交入库。差异原因在扫码数 ≠ 计划数时必填（BR-016，≥5 字）。"""

    reason: str | None = Field(None, max_length=255)


class VoidReq(BaseModel):
    reason: str = Field(..., min_length=1, max_length=255)


class InspectionListQuery(BaseModel):
    status: str | None = Field(None, pattern=r"^(PENDING|CHECKING|DONE)$")
    result: str | None = Field(None, pattern=r"^(PASS|PARTIAL|OVER_PASS|FAIL)$")
    no: str | None = None
    supplier_id: int | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class InspectionScanReq(BaseModel):
    """来料检验扫码。material_id + barcode 定位物料，actual_qty 是本次实收。"""

    material_id: int
    barcode: str | None = Field(None, max_length=64)
    actual_qty: int = Field(1, gt=0)


class InspectionJudgeReq(BaseModel):
    """检验判定。不合格必填原因（进供应商质量档案）。"""

    result: str = Field(..., pattern=r"^(PASS|PARTIAL|OVER_PASS|FAIL)$")
    fail_reason: str | None = Field(None, max_length=255)


class GenInboundReq(BaseModel):
    """已检合格 → 生成采购入库单。允许一个检验单拆多次入库。"""

    qty: int | None = Field(None, gt=0, description="本次入库数量，默认取剩余合格数")
    location_id: int | None = None
