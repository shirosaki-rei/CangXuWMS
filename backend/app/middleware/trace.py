"""请求级中间件：trace_id 贯穿、访问日志。"""
from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

log = get_logger("wms.http")


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex[:16]
        request.state.trace_id = trace_id
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        response.headers["x-trace-id"] = trace_id
        if not request.url.path.startswith(("/health", "/metrics")):
            log.info(
                "%s %s -> %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={
                    "trace_id": trace_id,
                    "user_id": getattr(request.state, "user_id", None),
                    "path": request.url.path,
                    "latency_ms": elapsed,
                    "code": response.headers.get("x-biz-code", "0"),
                },
            )
        return response
