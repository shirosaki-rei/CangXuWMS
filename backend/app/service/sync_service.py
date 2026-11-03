"""离线补传服务（接口 58 / 接口文档 3.8）。

APP 断网时把扫码操作写本地 SQLite 队列，恢复网络后按 created_at 升序批量补传。
服务端逐条执行、逐条返回，单条失败不影响后续（BR-012：冲突以服务端为准）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BizError, Codes
from app.core.redis import rds
from app.domain.models import OpLog, User

# 允许补传的白名单：op_type -> (HTTP 方法, 路径模板)
# 不在表里的一律拒绝——补传接口是重放入口，放开等于开了一个任意端点调用器
_ALLOWED_OPS: dict[str, tuple[str, str]] = {
    "INBOUND_SCAN": ("POST", "/api/v1/inbound-orders/{order_id}/scan"),
    "INBOUND_SUBMIT": ("POST", "/api/v1/inbound-orders/{order_id}/submit"),
    "INBOUND_VOID": ("POST", "/api/v1/inbound-orders/{order_id}/void"),
    "OUTBOUND_PICK": ("POST", "/api/v1/outbound-orders/{order_id}/pick"),
    "OUTBOUND_SUBMIT": ("POST", "/api/v1/outbound-orders/{order_id}/submit"),
    "OUTBOUND_VOID": ("POST", "/api/v1/outbound-orders/{order_id}/void"),
    "INSPECTION_SCAN": ("POST", "/api/v1/inspections/{inspection_id}/scan"),
    "INSPECTION_JUDGE": ("POST", "/api/v1/inspections/{inspection_id}/judge"),
}

MAX_BATCH = 50  # 接口文档 5.5：单次 ≤ 50 条

# op_type -> body 里承载单据 id 的字段名
_ID_FIELD = {
    "INBOUND_SCAN": "order_id", "INBOUND_SUBMIT": "order_id", "INBOUND_VOID": "order_id",
    "OUTBOUND_PICK": "order_id", "OUTBOUND_SUBMIT": "order_id", "OUTBOUND_VOID": "order_id",
    "INSPECTION_SCAN": "inspection_id", "INSPECTION_JUDGE": "inspection_id",
}


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def push(db: Session, ops, user_id: int) -> dict:
    """逐条执行补传。顺序由调用方保证（按 created_at 升序），这里再排一次兜底。"""
    if len(ops) > MAX_BATCH:
        raise BizError(Codes.BIZ_RULE, f"单次最多补传 {MAX_BATCH} 条，请分批",
                       data={"limit": MAX_BATCH})

    user = db.get(User, user_id)
    if user is None:
        raise BizError(Codes.UNAUTHORIZED, "账号不存在")

    ordered = sorted(ops, key=lambda o: _parse_dt(o.created_at) or datetime.min)
    results = []
    for op in ordered:
        results.append(_replay_one(db, op, user_id))
    return {"results": results, "total": len(results)}


def _replay_one(db: Session, op, user_id: int) -> dict:
    """单条补传。先查 op_log，命中就是重放；否则本地执行同一套业务逻辑。"""
    spec = _ALLOWED_OPS.get(op.op_type)
    if spec is None:
        return _fail(op.client_op_id, Codes.BAD_REQUEST, f"不支持的补传类型 {op.op_type}")

    # op_log 是幂等的最终判据（接口 1.3 第 5 条）
    row = db.execute(
        select(OpLog).where(OpLog.client_op_id == op.client_op_id)
    ).scalar_one_or_none()
    if row is not None:
        return {"client_op_id": op.client_op_id, "status": "DUPLICATE",
                "http_code": Codes.REPLAY, "data": row.result}

    key = f"idem:{op.client_op_id}"
    if not rds.set(key, "1", nx=True, ex=86400):
        return _fail(op.client_op_id, Codes.REPLAY, "操作正在处理中，请勿重复提交")

    try:
        data = _dispatch(db, op, spec, user_id)
    except BizError as e:
        rds.delete(key)
        return _fail(op.client_op_id, e.code, e.message)
    except Exception as e:  # noqa: BLE001
        rds.delete(key)
        return _fail(op.client_op_id, Codes.SERVER_ERROR, f"服务端异常：{type(e).__name__}")

    try:
        db.add(OpLog(client_op_id=op.client_op_id, user_id=user_id,
                     path=spec[1][:120], result=data))
        db.commit()
    except Exception:
        db.rollback()
    return {"client_op_id": op.client_op_id, "status": "OK", "http_code": Codes.OK,
            "data": data}


def _fail(op_id: str, code: str, message: str) -> dict:
    return {"client_op_id": op_id, "status": "FAILED", "http_code": code, "message": message}


def _dispatch(db: Session, op, spec: tuple[str, str], user_id: int):
    """按 op_type 调对应的 service。schema 由各 service 自己校验。"""
    from app.schemas.inbound import (
        GenInboundReq,
        InspectionJudgeReq,
        InspectionScanReq,
        ScanReq,
        SubmitReq,
        VoidReq,
    )
    from app.schemas.outbound import OutboundSubmitReq, OutboundVoidReq, PickReq
    from app.service import inbound_service, inspection_service, outbound_service

    body = op.body or {}
    doc_id = body.get(_ID_FIELD.get(op.op_type, ""))
    if doc_id is None:
        raise BizError(Codes.BAD_REQUEST, f"补传 body 缺少 {_ID_FIELD.get(op.op_type)}")

    table = {
        "INBOUND_SCAN": lambda: inbound_service.scan(db, doc_id, ScanReq(**body), user_id),
        "INBOUND_SUBMIT": lambda: inbound_service.submit(
            db, doc_id, SubmitReq(**{k: v for k, v in body.items() if k == "reason"}), user_id),
        "INBOUND_VOID": lambda: inbound_service.void(db, doc_id, VoidReq(**body), user_id),
        "OUTBOUND_PICK": lambda: outbound_service.pick(db, doc_id, PickReq(**body), user_id),
        "OUTBOUND_SUBMIT": lambda: outbound_service.submit(
            db, doc_id, OutboundSubmitReq(**{k: v for k, v in body.items() if k == "reason"}),
            user_id),
        "OUTBOUND_VOID": lambda: outbound_service.void(db, doc_id, OutboundVoidReq(**body), user_id),
        "INSPECTION_SCAN": lambda: inspection_service.scan(
            db, doc_id, InspectionScanReq(**body), user_id),
        "INSPECTION_JUDGE": lambda: inspection_service.judge(
            db, doc_id, InspectionJudgeReq(**body), user_id),
    }[op.op_type]
    return table()


def new_op_id() -> str:
    """客户端生成幂等键用；服务端也导出一份便于测试对齐。"""
    return str(uuid.uuid4())
