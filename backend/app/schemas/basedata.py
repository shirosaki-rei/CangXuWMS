"""基础资料（P18/P19/P20）与账号权限的请求 schema。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.enums import (
    BarcodeType,
    LocationStatus,
    LocationType,
    Role,
    Switch,
    TempControl,
    UserStatus,
    WarehouseType,
)


# ---------------------------------------------------------------- 仓库 P18
class WarehouseIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32, description="WH-001")
    name: str = Field(..., min_length=1, max_length=64)
    type: WarehouseType
    owner_id: int | None = None


class WarehouseUpdate(WarehouseIn):
    pass


class WarehouseOut(BaseModel):
    id: int
    code: str
    name: str
    type: str
    status: str
    owner_id: int | None = None
    location_count: int = 0
    created_at: str


class WarehouseToggle(BaseModel):
    status: Switch


# ---------------------------------------------------------------- 库位 P19
class LocationIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32, description="A1-01-01")
    name: str = Field(..., min_length=1, max_length=64)
    type: LocationType = LocationType.NORMAL
    warehouse_id: int
    cap_pallet: int = Field(0, ge=0)
    cap_material: int = Field(0, ge=0)
    coord_x: float | None = None
    coord_y: float | None = None
    dist_to_dock: float | None = None
    dist_to_pack: float | None = None


class LocationUpdate(LocationIn):
    pass


class LocationStatusIn(BaseModel):
    status: LocationStatus


class LocationOut(BaseModel):
    id: int
    code: str
    name: str
    type: str
    warehouse_id: int
    warehouse_name: str | None = None
    cap_pallet: int
    cap_material: int
    used_pallet: int
    status: str
    coord_x: float | None = None
    coord_y: float | None = None
    coord_missing: bool = False  # BR-025
    created_at: str


# ---------------------------------------------------------------- 条码 P20
class BarcodeIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64, description="KQ-001")
    type: BarcodeType
    ref_id: int | None = None


class BarcodePrintIn(BaseModel):
    ids: list[int] = Field(..., min_length=1)
    spec: str = Field("40x30", pattern=r"^(40x30|60x40)$")
    copies: int = Field(1, ge=1, le=100)


class BarcodeOut(BaseModel):
    id: int
    code: str
    type: str
    ref_id: int | None = None
    created_at: str


# ---------------------------------------------------------------- 账号与权限
class UserIn(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    name: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=6, max_length=64)
    phone: str | None = Field(None, max_length=20)
    role: Role


class UserUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    phone: str | None = Field(None, max_length=20)
    status: UserStatus | None = None
    password: str | None = Field(None, min_length=6, max_length=64)


class UserRolesIn(BaseModel):
    role: Role
    warehouse_ids: list[int] = Field(default_factory=list)


class UserOut(BaseModel):
    id: int
    username: str
    name: str
    phone: str | None = None
    role: str
    status: str
    warehouse_ids: list[int] = Field(default_factory=list)
    created_at: str


class RoleOut(BaseModel):
    value: str
    label: str


class SysConfigIn(BaseModel):
    cfg_key: str = Field(..., min_length=1, max_length=64)
    cfg_value: str = Field(..., max_length=255)
    value_type: str = Field("STRING", pattern=r"^(INT|DECIMAL|BOOL|ENUM|STRING)$")
    scope: str = Field("GLOBAL", pattern=r"^(GLOBAL|SUPPLIER)$")
    scope_id: int | None = None
    remark: str | None = Field(None, max_length=255)


class SysConfigOut(BaseModel):
    id: int
    cfg_key: str
    cfg_value: str
    value_type: str
    scope: str
    scope_id: int | None = None
    remark: str | None = None
    updated_at: str
