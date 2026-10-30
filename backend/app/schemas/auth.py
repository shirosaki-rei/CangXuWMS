"""认证相关 schema（接口文档 3.1）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CaptchaResp(BaseModel):
    captcha_id: str
    image: str  # SVG data URI
    ttl: int


class LoginReq(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=64)
    captcha_id: str = Field(..., min_length=1)
    captcha: str = Field(..., min_length=4, max_length=4)
    remember: bool = False


class LoginUser(BaseModel):
    id: int
    name: str
    role: str
    warehouses: list[dict] = Field(default_factory=list)


class LoginResp(BaseModel):
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: LoginUser
    landing: str = "/"


class RefreshReq(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class RefreshResp(BaseModel):
    access_token: str
    expires_in: int
    refresh_token: str


class MeResp(BaseModel):
    id: int
    username: str
    name: str
    phone: str | None = None
    role: str
    role_label: str = ""
    permissions: list[str] = Field(default_factory=list)
    warehouses: list[dict] = Field(default_factory=list)
