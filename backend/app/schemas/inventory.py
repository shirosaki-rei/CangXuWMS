"""库存与流水查询的请求 schema（接口 4/5/6，页面 P01–P04）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class InventoryQuery(BaseModel):
    name: str | None = None
    code: str | None = None
    # ISO 日期或日期时间都接受，service 负责归一
    date_from: str | None = None
    date_to: str | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class TxnQuery(BaseModel):
    """出入库流水。sku_type 二选一：PRODUCT 走 P03，MATERIAL 走 P04。"""

    sku_type: str = Field("PRODUCT", pattern=r"^(PRODUCT|MATERIAL)$")
    name: str | None = None
    code: str | None = None
    biz_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class ExportQuery(BaseModel):
    biz: str = Field(..., pattern=r"^(inventory_products|inventory_materials|txn)$")
    sku_type: str | None = Field(None, pattern=r"^(PRODUCT|MATERIAL)$")
    name: str | None = None
    code: str | None = None
    biz_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None
