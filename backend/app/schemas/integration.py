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


class OutboundPushReq(BaseModel):
    """MES → WMS 销售发货指令（接口 4.3）。"""

    no: str = Field(..., max_length=32, description="SO + yyyyMMdd + 3 位流水")
    version: int = Field(1, ge=1)
    sales_order_no: str | None = Field(None, max_length=32)
    product_code: str = Field(..., max_length=64)
    plan_qty: int = Field(..., gt=0)
    delivery_date: str | None = None


class PickItemIn(BaseModel):
    material_code: str = Field(..., max_length=64)
    qty: int = Field(..., gt=0)


class PickPushReq(BaseModel):
    """MES → WMS 领料需求（接口 4.5）。"""

    no: str = Field(..., max_length=32, description="PL + yyyyMMdd + 3 位流水")
    version: int = Field(1, ge=1)
    task_no: str | None = Field(None, max_length=32)
    items: list[PickItemIn] = Field(..., min_length=1)


class ProductionInboundReq(BaseModel):
    """MES → WMS 完工入库（接口 4.4）。"""

    no: str = Field(..., max_length=32, description="PI + yyyyMMdd + 3 位流水")
    version: int = Field(1, ge=1)
    task_no: str | None = Field(None, max_length=32)
    box_code: str | None = Field(None, max_length=64)
    product_code: str = Field(..., max_length=64)
    qty: int = Field(..., gt=0)
