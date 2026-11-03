"""出库单与离线同步的请求 schema（接口 9/10/28/29/38/58，页面 P10–P13）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class OutboundListQuery(BaseModel):
    type: str | None = Field(None, pattern=r"^(SALES|PICK|LOSS)$")
    status: str | None = Field(None, pattern=r"^(PENDING|PARTIAL|DONE|VOID)$")
    no: str | None = None
    source_no: str | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class PickReq(BaseModel):
    """扫码拣货。逐件出库必须带 SN；location_id 是发货库位。"""

    sn: str | None = Field(None, max_length=64)
    location_id: int = Field(..., description="发货库位")
    qty: int = Field(1, gt=0)


class OutboundSubmitReq(BaseModel):
    """提交出库。实发 < 计划时必须填原因（BR-016）。"""

    reason: str | None = Field(None, max_length=255)


class OutboundVoidReq(BaseModel):
    reason: str = Field(..., min_length=1, max_length=255)


class SyncOp(BaseModel):
    """离线补传单条。path + body 原样重放到对应接口。"""

    client_op_id: str = Field(..., min_length=8, max_length=64)
    op_type: str = Field(..., max_length=32)
    path: str = Field(..., max_length=120)
    body: dict = Field(default_factory=dict)
    created_at: str | None = None


class SyncPushReq(BaseModel):
    ops: list[SyncOp] = Field(..., min_length=1)
