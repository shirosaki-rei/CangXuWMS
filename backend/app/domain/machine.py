"""单据状态机（PRD 第 9 章）。所有状态推进只经此处，service 不得直接赋 status。

设计：迁移表是纯数据，`transit()` 是唯一写入口。加一种单据只加一行。
"""
from __future__ import annotations

from app.core.errors import BizError, Codes
from app.domain.enums import (
    InspectionStatus,
    MoveStatus,
    OrderStatus,
    StocktakeStatus,
)

# 单据类型 -> {当前状态: 允许的下一状态}
TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "INBOUND": {
        OrderStatus.PENDING: {OrderStatus.PARTIAL, OrderStatus.DONE, OrderStatus.VOID},
        OrderStatus.PARTIAL: {OrderStatus.DONE, OrderStatus.VOID},
    },
    "OUTBOUND": {
        OrderStatus.PENDING: {OrderStatus.PARTIAL, OrderStatus.DONE, OrderStatus.VOID},
        OrderStatus.PARTIAL: {OrderStatus.DONE, OrderStatus.VOID},
    },
    "INSPECTION": {
        InspectionStatus.PENDING: {InspectionStatus.CHECKING},
        InspectionStatus.CHECKING: {InspectionStatus.DONE},
    },
    "STOCKTAKE": {
        StocktakeStatus.PENDING: {StocktakeStatus.COUNTING, StocktakeStatus.CANCELED},
        StocktakeStatus.COUNTING: {StocktakeStatus.CONFIRMING, StocktakeStatus.CANCELED},
        StocktakeStatus.CONFIRMING: {StocktakeStatus.DONE},
    },
    "MOVE": {
        MoveStatus.PENDING: {MoveStatus.DOING},
        MoveStatus.DOING: {MoveStatus.DONE},
    },
}

TERMINAL: dict[str, set[str]] = {
    "INBOUND": {OrderStatus.DONE, OrderStatus.VOID},
    "OUTBOUND": {OrderStatus.DONE, OrderStatus.VOID},
    "INSPECTION": {InspectionStatus.DONE},
    "STOCKTAKE": {StocktakeStatus.DONE, StocktakeStatus.CANCELED},
    "MOVE": {MoveStatus.DONE},
}

# 需要作废原因的单据类型（BR-011）
_VOID_TYPES = {"INBOUND", "OUTBOUND"}
_VOID_STATES = {OrderStatus.VOID, StocktakeStatus.CANCELED}


class IllegalTransition(BizError):
    def __init__(self, doc_type: str, cur: str, nxt: str) -> None:
        super().__init__(Codes.BIZ_RULE, f"单据状态不允许从「{cur}」变为「{nxt}」")
        self.doc_type, self.cur, self.nxt = doc_type, cur, nxt


def known(doc_type: str) -> bool:
    return doc_type in TRANSITIONS


def is_terminal(doc_type: str, status: str) -> bool:
    return status in TERMINAL.get(doc_type, set())


def can_transit(doc_type: str, cur: str, nxt: str) -> bool:
    return nxt in TRANSITIONS.get(doc_type, {}).get(cur, set())


def transit(doc_type: str, cur: str, nxt: str, *, reason: str | None = None) -> str:
    """校验并返回新状态。非法迁移抛 WMS-4221；作废缺原因抛 WMS-4001。

    顺序很重要：终态校验必须在「同态直接返回」之前，否则终态单据可以被反复作废。
    """
    if not known(doc_type):
        raise BizError(Codes.SERVER_ERROR, f"未登记的单据类型 {doc_type}")
    if is_terminal(doc_type, cur):
        raise BizError(Codes.ORDER_CLOSED, f"单据已终态（{cur}），不可再变更")
    if cur == nxt:
        return cur
    if not can_transit(doc_type, cur, nxt):
        raise IllegalTransition(doc_type, cur, nxt)
    if nxt in _VOID_STATES and doc_type in _VOID_TYPES and not (reason or "").strip():
        raise BizError(Codes.BAD_REQUEST, "作废必须填写原因")
    return nxt


def advance_by_qty(doc_type: str, cur: str, done_qty: int, plan_qty: int) -> str:
    """按实扫/实发数量推进入库单、出库单状态。计划数为 0 时直接完成。"""
    if doc_type not in ("INBOUND", "OUTBOUND"):
        raise BizError(Codes.SERVER_ERROR, f"{doc_type} 不走数量推进")
    nxt = OrderStatus.DONE if done_qty >= plan_qty else OrderStatus.PARTIAL
    return transit(doc_type, cur, nxt)


# ---------------------------------------------------------------- 自测
def _self_check() -> None:  # pragma: no cover - `python -m app.domain.machine` 跑
    from app.core.errors import BizError as E

    assert can_transit("INBOUND", "PENDING", "PARTIAL")
    assert can_transit("INBOUND", "PARTIAL", "DONE")
    assert not can_transit("INBOUND", "DONE", "PENDING"), "终态不可回退"
    assert not can_transit("INBOUND", "DONE", "VOID"), "终态不可再作废"
    assert not can_transit("INBOUND", "PENDING", "CHECKING"), "跨类型迁移"
    assert advance_by_qty("INBOUND", "PENDING", 100, 100) == "DONE"
    assert advance_by_qty("INBOUND", "PENDING", 12, 100) == "PARTIAL"
    assert transit("INBOUND", "PENDING", "PENDING") == "PENDING", "同态直接返回"
    try:
        transit("INBOUND", "PENDING", "VOID")
    except E as e:
        assert e.code == Codes.BAD_REQUEST, "作废缺原因必须报 4001"
    else:
        raise AssertionError("作废缺原因未拦截")
    try:
        transit("INBOUND", "DONE", "VOID")
    except E as e:
        assert e.code == Codes.ORDER_CLOSED, "终态必须报 4092"
    else:
        raise AssertionError("终态回退未拦截")
    try:
        transit("STOCKTAKE", "CONFIRMING", "COUNTING")
    except E:
        pass
    else:
        raise AssertionError("盘点回退未拦截")
    # 终态同态（已作废再作废）必须被终态校验拦住，不能被「同态直接返回」放过
    try:
        transit("INBOUND", "VOID", "VOID", reason="再作废")
    except E as e:
        assert e.code == Codes.ORDER_CLOSED, "终态同态必须报 4092"
    else:
        raise AssertionError("终态同态未拦截")
    print("machine self-check ok")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
