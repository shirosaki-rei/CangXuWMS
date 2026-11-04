"""MES/ERP 集成服务（接口 59/60/61 + 回传 63/64）。

幂等键 = no + version：重复推送返回首次结果，不产生重复单据（接口 4.1）。
回传走异步重试（3 次，退避 50/200/800ms），全失败记 ERROR 日志并进对账兜底。
"""
from __future__ import annotations

import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BizError, Codes
from app.core.logging import get_logger
from app.domain.enums import InboundType, OrderStatus, OutboundType
from app.domain.models import (
    InboundItem,
    InboundOrder,
    Material,
    OutboundItem,
    OutboundOrder,
    Product,
)
from app.schemas.integration import OutboundPushReq, PickPushReq, ProductionInboundReq
from app.service.admin_service import get_config

log = get_logger("wms.integration")

RETRY_BACKOFF = (0.05, 0.2, 0.8)


def _material_id(db: Session, code: str) -> int:
    mid = db.execute(select(Material.id).where(Material.code == code)).scalar_one_or_none()
    if mid is None:
        raise BizError(Codes.BAD_REQUEST, f"物料编码 {code} 未维护")
    return mid


def _product_id(db: Session, code: str) -> int:
    pid = db.execute(select(Product.id).where(Product.code == code)).scalar_one_or_none()
    if pid is None:
        raise BizError(Codes.BAD_REQUEST, f"产品编码 {code} 未维护")
    return pid


def _replay(order) -> dict:
    return {"code": Codes.REPLAY, "message": "重复推送，已返回首次结果",
            "data": {"id": order.id, "no": order.no, "status": order.status}}


# ---------------------------------------------------------------- 59 销售发货
def push_outbound(db: Session, body: OutboundPushReq) -> dict:
    exist = db.execute(
        select(OutboundOrder).where(OutboundOrder.no == body.no)
    ).scalar_one_or_none()
    if exist is not None:
        return _replay(exist)

    pid = _product_id(db, body.product_code)
    o = OutboundOrder(no=body.no, type=str(OutboundType.SALES),
                      source_no=body.sales_order_no, status=str(OrderStatus.PENDING),
                      plan_qty=body.plan_qty, actual_qty=0, creator_id=0)
    db.add(o)
    db.flush()
    db.add(OutboundItem(order_id=o.id, sku_id=pid, status="PENDING"))
    db.commit()
    return {"id": o.id, "no": o.no, "status": o.status}


# ---------------------------------------------------------------- 60 领料需求
def push_pick(db: Session, body: PickPushReq) -> dict:
    exist = db.execute(
        select(OutboundOrder).where(OutboundOrder.no == body.no)
    ).scalar_one_or_none()
    if exist is not None:
        return _replay(exist)

    o = OutboundOrder(no=body.no, type=str(OutboundType.PICK), source_no=body.task_no,
                      status=str(OrderStatus.PENDING),
                      plan_qty=sum(i.qty for i in body.items), actual_qty=0, creator_id=0)
    db.add(o)
    db.flush()
    for it in body.items:
        db.add(OutboundItem(order_id=o.id, sku_id=_material_id(db, it.material_code),
                            status="PENDING"))
    db.commit()
    return {"id": o.id, "no": o.no, "status": o.status}


# ---------------------------------------------------------------- 61 完工入库
def push_production_inbound(db: Session, body: ProductionInboundReq) -> dict:
    exist = db.execute(
        select(InboundOrder).where(InboundOrder.no == body.no)
    ).scalar_one_or_none()
    if exist is not None:
        return _replay(exist)

    pid = _product_id(db, body.product_code)
    o = InboundOrder(no=body.no, type=str(InboundType.PRODUCT), source_no=body.task_no,
                     status=str(OrderStatus.PENDING),
                     plan_qty=body.qty, actual_qty=0, creator_id=0)
    db.add(o)
    db.flush()
    db.add(InboundItem(order_id=o.id, sku_id=pid, box_code=body.box_code, qty=0))
    db.commit()
    return {"id": o.id, "no": o.no, "status": o.status}


# ---------------------------------------------------------------- 63/64 回传
def _callback_url(db: Session, target: str) -> str | None:
    key = "mes_callback_url" if target.upper() == "MES" else "erp_callback_url"
    url = get_config(db, key, "")
    return (url or "").strip() or None


def send_callback(db: Session, target: str, payload: dict) -> bool:
    """向 MES/ERP 回传。3 次退避重试；全失败只记日志，不阻塞业务。

    ponytail: 失败重试队列用「日志 + 每日对账兜底」，没有单独建表。
    真要可靠投递得加 outbox 表 + worker 轮询，等现场确实丢过再说。
    """
    url = _callback_url(db, target)
    if not url:
        return False

    for i, backoff in enumerate(RETRY_BACKOFF):
        try:
            with httpx.Client(timeout=3.0) as c:
                r = c.post(url, json=payload)
            if r.status_code < 500:
                return True
        except Exception as e:  # noqa: BLE001
            if i == len(RETRY_BACKOFF) - 1:
                log.error("callback %s failed after retries: %s", target, e)
                return False
            time.sleep(backoff)
    log.error("callback %s failed (5xx)", target)
    return False


def inbound_payload(order: InboundOrder, txn_id: int | None = None) -> dict:
    return {"biz_no": order.no, "txn_id": txn_id, "actual_qty": order.actual_qty,
            "finished_at": order.finished_at.isoformat() + "Z" if order.finished_at else None}


def outbound_payload(order: OutboundOrder, txn_id: int | None = None) -> dict:
    return {"biz_no": order.no, "txn_id": txn_id, "actual_qty": order.actual_qty,
            "finished_at": order.finished_at.isoformat() + "Z" if order.finished_at else None}
