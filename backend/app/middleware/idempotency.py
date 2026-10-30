"""幂等中间件（接口文档 1.3）。

协议：
  1. 写请求带 X-Client-Op-Id（接口 1.3 的首选位置）
  2. Redis SETNX idem:{op_id}（TTL 24h）→ 首次放行
  3. 首次：执行业务，把完整响应 data 写 op_log.result
  4. 重放：SETNX 失败 → 查 op_log → 原样返回首次结果，code=WMS-4091
  5. Redis 键过期后的重放：op_log.uk_client_op 兜底，行为同 4

失败不落 op_log 并删掉 Redis 键，让客户端重试能真正重跑。

ponytail: client_op_id 只认 Header，不读 body——BaseHTTPMiddleware 提前读 body 会把流耗尽，
下游拿不到数据。PC 端与 APP 都在我们手里，统一发 Header 即可；body 字段留给外部调用方自便。
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.errors import BizError, Codes
from app.core.logging import get_logger
from app.core.redis import rds
from app.domain.models import OpLog

log = get_logger("wms.idem")

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# 不走幂等：登录/验证码无 client_op_id；登出是本地会话作废；集成端用 no+version；导出走异步任务
_EXEMPT_PREFIX = (
    "/auth/login", "/auth/refresh", "/auth/captcha", "/auth/logout",
    "/integration/", "/export/", "/health", "/metrics", "/docs", "/openapi", "/redoc",
)


def _exempt(path: str) -> bool:
    """按去掉 API 前缀后的路径判断。"""
    p = path[len(settings.api_prefix):] if path.startswith(settings.api_prefix) else path
    return any(p.startswith(x) for x in _EXEMPT_PREFIX)


def _json(body: bytes, payload: dict, status: int) -> Response:
    return Response(json.dumps(payload, ensure_ascii=False, default=str),
                    media_type="application/json; charset=utf-8", status_code=status)


def _replay(request: Request, row: OpLog | None) -> Response:
    trace_id = getattr(request.state, "trace_id", "")
    if row is None:
        return _json({}, BizError(Codes.REPLAY, "操作正在处理中，请勿重复提交").payload(trace_id), 200)
    return _json({}, {"code": Codes.REPLAY, "message": "重复提交，已返回首次结果",
                      "data": row.result, "trace_id": trace_id}, 200)


def _lookup(op_id: str) -> OpLog | None:
    with SessionLocal() as s:
        return s.execute(select(OpLog).where(OpLog.client_op_id == op_id)).scalar_one_or_none()


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if request.method not in _MUTATING or _exempt(path):
            return await call_next(request)

        op_id = (request.headers.get("x-client-op-id") or "").strip()
        if not op_id:
            return _json({}, BizError(
                Codes.BAD_REQUEST, "写操作必须带 client_op_id（Header: X-Client-Op-Id）"
            ).payload(getattr(request.state, "trace_id", "")), 400)

        # op_log 是权威来源：Redis 键可能已过期，DB 里的记录才是最终判据
        row = _lookup(op_id)
        if row is not None:
            log.info("replay(op_log) op_id=%s path=%s", op_id, path)
            return _replay(request, row)

        key = f"idem:{op_id}"
        if not rds.set(key, "1", nx=True, ex=settings.idempotency_ttl):
            # Redis 说见过但 DB 没记录 → 首次请求还在处理中
            log.info("replay(in-flight) op_id=%s path=%s", op_id, path)
            return _replay(request, None)

        response = await call_next(request)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            payload = json.loads(body) if body else None
        except (ValueError, TypeError):
            payload = None

        if payload is not None and payload.get("code") == Codes.OK:
            try:
                with SessionLocal() as s:
                    s.add(OpLog(client_op_id=op_id,
                                user_id=getattr(request.state, "user_id", None),
                                path=path[:120], result=payload.get("data")))
                    s.commit()
            except IntegrityError:
                # 并发下另一请求已落账 → 以它的结果为准
                log.info("replay(race) op_id=%s path=%s", op_id, path)
                row = _lookup(op_id)
                headers = {k: v for k, v in response.headers.items()
                           if k.lower() != "content-length"}
                return _replay(request, row)
        else:
            rds.delete(key)  # 失败不占坑

        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(content=body, status_code=response.status_code, headers=headers,
                        media_type=response.media_type)
