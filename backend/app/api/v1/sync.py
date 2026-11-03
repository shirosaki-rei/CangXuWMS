"""离线补传接口（接口 58）。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.deps import CurrentUser, DbDep
from app.core.errors import ok
from app.schemas.outbound import SyncPushReq
from app.service import sync_service as svc

router = APIRouter(prefix="/sync", tags=["离线同步"])


@router.post("/push", summary="批量补传（接口 58，单次 ≤ 50 条）")
def push(request: Request, db: DbDep, body: SyncPushReq, user: CurrentUser) -> dict:
    """按 created_at 升序逐条执行，逐条返回，单条失败不影响后续（BR-012）。"""
    return ok(svc.push(db, body.ops, user.id), trace_id=request.state.trace_id)
