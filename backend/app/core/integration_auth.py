"""集成端认证：HMAC-SHA256 签名（接口文档 4.1）。

    X-App-Key:   mes-prod
    X-Timestamp: 1769498400            # 秒级，偏差 > 300s 拒绝 → WMS-4011
    X-Sign:      hex(hmac_sha256(app_secret, app_key + timestamp + body_raw))

做成 FastAPI 依赖而不是中间件：签名只对 /integration/* 生效，依赖更直白，
也不会给用户端接口平添一次解析。改造点只有这一处（接口文档 I-04）。
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_session
from app.core.errors import BizError, Codes
from app.domain.models import ApiClient

TIMESTAMP_TOLERANCE = 300  # 秒


def sign(app_secret: str, app_key: str, timestamp: str, body: bytes) -> str:
    """签名算法。测试与对端都用这一个函数，避免两边各写一份。"""
    msg = f"{app_key}{timestamp}".encode() + body
    return hmac.new(app_secret.encode(), msg, hashlib.sha256).hexdigest()


def verify(request: Request, db: Session = Depends(get_session)) -> ApiClient:
    app_key = request.headers.get("x-app-key", "")
    timestamp = request.headers.get("x-timestamp", "")
    signature = request.headers.get("x-sign", "")

    if not (app_key and timestamp and signature):
        raise BizError(Codes.SIGN_INVALID, "缺少集成端签名头（X-App-Key / X-Timestamp / X-Sign）")

    try:
        ts = int(timestamp)
    except ValueError:
        raise BizError(Codes.SIGN_INVALID, "X-Timestamp 必须是秒级 Unix 时间戳") from None
    if abs(time.time() - ts) > TIMESTAMP_TOLERANCE:
        raise BizError(Codes.SIGN_INVALID,
                       f"时间戳偏差超过 {TIMESTAMP_TOLERANCE} 秒，拒绝服务（防重放）")

    client = db.execute(
        select(ApiClient).where(ApiClient.app_key == app_key)
    ).scalar_one_or_none()
    if client is None or client.status != "ENABLED":
        # 不暴露账号是否存在
        raise BizError(Codes.SIGN_INVALID, "签名错误")

    body = getattr(request.state, "raw_body", b"")
    expect = sign(client.app_secret, app_key, timestamp, body)
    if not hmac.compare_digest(expect, signature.lower()):
        raise BizError(Codes.SIGN_INVALID, "签名错误")

    request.state.app_client = client
    return client


IntegrationClient = Annotated[ApiClient, Depends(verify)]
