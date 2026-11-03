"""原始 body 缓存（只对集成接口生效）。

集成端签名是对 `body_raw` 算 HMAC，必须先拿到原始字节。做成纯 ASGI 中间件而不是
BaseHTTPMiddleware：后者会把整个响应体缓冲下来，还会吃掉 body 让下游读不到。
这里只对集成接口前缀动手，其余路由零额外开销。
"""
from __future__ import annotations

from typing import MutableMapping

from app.core.config import settings

# 必须是完整路径前缀（含 api_prefix），否则匹配不上任何请求
INTEGRATION_PREFIX = f"{settings.api_prefix}/integration/"


class RawBodyMiddleware:
    def __init__(self, app, prefix: str = INTEGRATION_PREFIX) -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(self.prefix):
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            chunks.append(msg.get("body", b"") or b"")
            if not msg.get("more_body", False):
                break
        body = b"".join(chunks)

        # Starlette 的 Request.state 就是 scope["state"] 的包装，先塞进去下游就能读到
        state: MutableMapping = scope.setdefault("state", {})
        state["raw_body"] = body

        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)
