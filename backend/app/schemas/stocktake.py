"""盘点与移位的请求 schema（接口 13–17、30–33，页面 P15–P17）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class StocktakeListQuery(BaseModel):
    no: str | None = None
    type: str | None = Field(None, pattern=r"^(FULL|SPOT|CYCLE)$")
    status: str | None = Field(None, pattern=r"^(PENDING|COUNTING|CONFIRMING|DONE|CANCELED)$")
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class StocktakeCreateReq(BaseModel):
    """创建盘点单。mode 不传则取 sys_config 的默认（BR-024：生产默认盲盘）。"""

    warehouse_id: int
    type: str = Field("FULL", pattern=r"^(FULL|SPOT|CYCLE)$")
    mode: str | None = Field(None, pattern=r"^(BLIND|OPEN)$")
    # 抽盘 / 循环盘点可指定库位；不传则整仓
    location_ids: list[int] | None = None


class CountReq(BaseModel):
    """提交实盘数。real_qty 为 0 与「未盘」是两回事——未盘是不调这个接口。"""

    location_id: int
    material_id: int
    real_qty: int = Field(..., ge=0)


class StocktakeSubmitReq(BaseModel):
    note: str | None = Field(None, max_length=255)


class MoveCreateReq(BaseModel):
    """移位：总量不变，只改库位维度。APP 侧的三扫由前端保证顺序。"""

    material_id: int
    from_location_id: int
    to_location_id: int
    qty: int = Field(..., gt=0)


class MoveListQuery(BaseModel):
    no: str | None = None
    material_id: int | None = None
    status: str | None = Field(None, pattern=r"^(PENDING|DOING|DONE)$")
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class SupplierListQuery(BaseModel):
    code: str | None = None
    name: str | None = None
    status: str | None = Field(None, pattern=r"^(ENABLED|DISABLED)$")


class SupplierUpdateReq(BaseModel):
    """BR-023：over_receive 为该供应商的超收阈值覆盖值，null 表示回落到全局默认。"""

    name: str | None = Field(None, min_length=1, max_length=128)
    over_receive: float | None = Field(None, ge=0, le=1)
    contact: str | None = Field(None, max_length=64)
    status: str | None = Field(None, pattern=r"^(ENABLED|DISABLED)$")
