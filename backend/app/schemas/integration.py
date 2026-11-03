"""集成接口请求 schema（接口文档 4.2–4.5）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class InspectionItemIn(BaseModel):
    material_code: str = Field(..., max_length=64)
    plan_qty: int = Field(..., gt=0)


class InspectionPushReq(BaseModel):
    """MES → WMS 检验任务（接口 4.2）。幂等键 = no + version。"""

    no: str = Field(..., max_length=32, description="JY + yyyyMMdd + 3 位流水")
    version: int = Field(1, ge=1)
    supplier_code: str = Field(..., max_length=32)
    logistics_no: str | None = Field(None, max_length=64)
    plate_no: str | None = Field(None, max_length=32)
    items: list[InspectionItemIn] = Field(..., min_length=1)
