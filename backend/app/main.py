"""FastAPI 实例、中间件、路由挂载（T-00-1）。"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import (
    admin,
    ai,
    auth,
    base_data,
    inbound,
    inspection,
    integration,
    inventory,
    outbound,
    stocktake,
    sync,
)
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.errors import Codes, ok, register_error_handlers
from app.core.logging import get_logger, setup_logging
from app.middleware.idempotency import IdempotencyMiddleware
from app.middleware.raw_body import RawBodyMiddleware
from app.middleware.trace import TraceMiddleware
from app.core.redis import rds

log = get_logger("wms")

STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    log.info("wms api starting env=%s redis=%s", settings.env, rds.backend)
    yield
    log.info("wms api stopped")
    engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="仓序 WMS · 仓储管理系统 API",
        version="1.0.0",
        description="接口契约以 `docs/WMS接口文档.md` 为单一数据源。",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # 中间件顺序：后添加的先执行 → Trace 最外层，原始 body 缓存最靠内（只对 /integration/）
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(TraceMiddleware)
    app.add_middleware(RawBodyMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-trace-id"],
    )

    register_error_handlers(app)

    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(base_data.router, prefix=prefix)
    app.include_router(base_data.loc_router, prefix=prefix)
    app.include_router(base_data.bar_router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)
    app.include_router(inventory.router, prefix=prefix)
    app.include_router(inspection.router, prefix=prefix)
    app.include_router(inbound.router, prefix=prefix)
    app.include_router(integration.router, prefix=prefix)
    app.include_router(outbound.router, prefix=prefix)
    app.include_router(sync.router, prefix=prefix)
    app.include_router(stocktake.router, prefix=prefix)
    app.include_router(ai.router, prefix=prefix)

    @app.get("/health", tags=["运维"], summary="健康检查（T-00-1 交付物）")
    def health(request: Request) -> dict:
        checks = {}
        try:
            with SessionLocal() as s:
                s.execute(text("SELECT 1"))
            checks["db"] = "up"
        except Exception as e:  # noqa: BLE001
            checks["db"] = f"down: {type(e).__name__}"
        checks["redis"] = "up" if rds.backend == "redis" else "memory(fallback)"
        degraded = checks["db"] != "up"
        return ok(
            {
                "status": "degraded" if degraded else "ok",
                "env": settings.env,
                "uptime_s": round(time.time() - STARTED_AT, 1),
                "checks": checks,
            },
            trace_id=request.state.trace_id,
        )

    @app.get("/metrics", tags=["运维"], summary="Prometheus 指标（架构 9.5）")
    def metrics() -> str:
        from app.middleware.trace import STATS

        body = [
            "# HELP wms_uptime_seconds 进程运行秒数",
            "# TYPE wms_uptime_seconds gauge",
            f"wms_uptime_seconds {time.time() - STARTED_AT:.0f}",
            "# HELP wms_requests_total 请求总数",
            "# TYPE wms_requests_total counter",
            f"wms_requests_total {STATS['requests']}",
            "# HELP wms_errors_total 5xx 请求数",
            "# TYPE wms_errors_total counter",
            f"wms_errors_total {STATS['errors']}",
            "# HELP wms_slow_requests_total 超过 1.5s 的请求数",
            "# TYPE wms_slow_requests_total counter",
            f"wms_slow_requests_total {STATS['slow']}",
            "# HELP wms_db_up 数据库连通性",
            "# TYPE wms_db_up gauge",
        ]
        try:
            with SessionLocal() as s:
                s.execute(text("SELECT 1"))
            body.append("wms_db_up 1")
        except Exception:  # noqa: BLE001
            body.append("wms_db_up 0")
        return "\n".join(body) + "\n"

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
