"""接口限流（接口文档 5.5）。

| 对象 | 限额 |
|---|---|
| LLM 调用 | 60 次/分/用户（在 llm_gateway 里单独做） |
| `/ai/query` | 全局 300 次/分 |
| `/sync/push` | 用户级 10 次/分 |
| 普通写接口 | 用户级 600 次/分 |
| 集成接口 | 按 app_key 1000 次/分 |

用固定窗口（Redis INCR + 60s TTL）：实现三行，够用。滑动窗口的精度在这里没有价值，
超限本来就是让客户端退避（接口文档写的是「指数退避重试」）。
"""
from __future__ import annotations

import hashlib
import json
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.errors import Codes
from app.core.redis import rds

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# 注意要带 api_prefix：登录/验证码请求没有 Authorization，若被限流会把人挡在门外
_EXEMPT_PREFIX = ("/health", "/metrics", "/docs", "/openapi", "/redoc",
                  "/api/v1/auth/captcha", "/api/v1/auth/login", "/api/v1/auth/refresh")


def _identity(request: Request) -> str:
    """优先用 token 摘要，其次 App-Key，最后退到 IP。

    中间件跑在鉴权之前，拿不到 user_id；用 Authorization 头的摘要做键，
    既能在登录后按人限流，也不用在这里解析/校验 JWT。
    """
    auth = request.headers.get("authorization")
    if auth:
        return "u:" + hashlib.sha1(auth.encode()).hexdigest()[:16]
    app_key = request.headers.get("x-app-key")
    if app_key:
        return "k:" + app_key
    return "ip:" + (request.client.host if request.client else "-")


def _bucket(request: Request) -> tuple[str, int] | None:
    """返回 (限流桶名, 每分钟上限)；不受限的请求返回 None。"""
    path = request.url.path
    if any(path.startswith(p) for p in _EXEMPT_PREFIX):
        return None

    if path.startswith(f"{settings.api_prefix}/integration/"):
        return "integration", settings.rl_integration
    if path == f"{settings.api_prefix}/sync/push":
        return "sync", settings.rl_sync_push
    if path == f"{settings.api_prefix}/ai/query":
        return "aiquery", settings.rl_ai_query  # 全局桶
    if request.method in _WRITE_METHODS:
        return "write", settings.rl_write
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        spec = _bucket(request)
        if spec is None:
            return await call_next(request)

        name, limit = spec
        # /ai/query 是全局桶，不按身份区分
        key = f"rl:{name}:{int(time.time() // 60)}" if name == "aiquery" \
            else f"rl:{name}:{_identity(request)}:{int(time.time() // 60)}"

        try:
            n = rds.incr(key)
            if n == 1:
                rds.expire(key, 60)
        except Exception:  # noqa: BLE001 —— Redis 挂了不能把业务也拖死
            return await call_next(request)

        if n > limit:
            payload = {
                "code": Codes.RATE_LIMIT,
                "message": f"操作过于频繁，请稍后重试（{limit} 次/分钟）",
                "data": {"bucket": name, "limit": limit},
                "trace_id": getattr(request.state, "trace_id", ""),
            }
            return Response(json.dumps(payload, ensure_ascii=False),
                            status_code=429,
                            media_type="application/json; charset=utf-8")
        return await call_next(request)
