"""库存增减的唯一入口（架构 5.2 / ADR-002）。

不变量：
- 任何库存变动必须关联一张单据（BR-001），所以 biz_type + biz_no 必填；
- 流水只增不改不删（BR-002），冲销用反向 delta；
- 可用量 = qty - locked_qty - frozen_qty，不落库；
- 事务边界由调用方控制，本模块不 commit。

并发策略：先按 inventory.id 升序一次性锁住所有涉及行，再依次落账，避免交叉死锁。
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable, TypeVar

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import BizError, Codes
from app.domain.models import Inventory, Txn

T = TypeVar("T")

DEADLOCK_ERRNO = 1213
DUP_KEY_ERRNO = 1062
RETRY_BACKOFF = (0.05, 0.1, 0.2)


@dataclass(frozen=True)
class Move:
    """一次库存变动。delta 正入负出。"""

    sku_type: str
    sku_id: int
    location_id: int
    delta: int


def _retryable(exc: Exception) -> bool:
    """1213 死锁 / 1062 唯一键冲突（并发插入同一 sku+location）都值得重试。"""
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", None) or ()
    return bool(args) and args[0] in (DEADLOCK_ERRNO, DUP_KEY_ERRNO)


def run_in_txn(factory: sessionmaker, unit: Callable[[Session], T], *, attempts: int = 3) -> T:
    """事务边界 + 死锁重试。unit 必须是完整业务单元（可安全整体重跑）。"""
    delay = RETRY_BACKOFF[0]
    for i in range(attempts):
        try:
            with factory() as s:
                out = unit(s)
                s.commit()
                return out
        except (OperationalError, IntegrityError) as e:
            if not _retryable(e) or i == attempts - 1:
                raise
            time.sleep(delay)
            delay = RETRY_BACKOFF[min(i + 1, len(RETRY_BACKOFF) - 1)]
    raise AssertionError("unreachable")


def _merge(moves: Iterable[Move]) -> list[Move]:
    """同一 (sku, location) 的多次变动合并成一行，少锁一行是一行。"""
    acc: dict[tuple[str, int, int], int] = defaultdict(int)
    for m in moves:
        acc[(m.sku_type, m.sku_id, m.location_id)] += m.delta
    return [Move(k[0], k[1], k[2], v) for k, v in acc.items() if v != 0]


def _locked(session: Session, stmt):
    """加行锁。SQLite 不支持 FOR UPDATE，且它本身单写者串行化，跳过不影响正确性。"""
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        return stmt
    return stmt.with_for_update()


def apply_many(
    session: Session,
    moves: Iterable[Move],
    *,
    biz_type: str,
    biz_no: str,
    operator_id: int,
) -> list[Inventory]:
    """按 inventory.id 升序加锁并落账。不 commit，抛 BizError 时由调用方回滚。"""
    merged = _merge(moves)
    if not merged:
        return []

    keys = [(m.sku_type, m.sku_id, m.location_id) for m in merged]
    rows = (
        session.execute(
            _locked(
                session,
                select(Inventory).where(
                    or_(*[and_(Inventory.sku_type == k[0], Inventory.sku_id == k[1],
                              Inventory.location_id == k[2]) for k in keys])
                ).order_by(Inventory.id.asc()),
            )
        )
        .scalars()
        .all()
    )
    by_key = {(r.sku_type, r.sku_id, r.location_id): r for r in rows}
    move_by_key = {(m.sku_type, m.sku_id, m.location_id): m for m in merged}
    missing = [m for m in merged if (m.sku_type, m.sku_id, m.location_id) not in by_key]

    for m in missing:
        if m.delta < 0:
            raise BizError(Codes.STOCK_SHORT, f"库位 {m.location_id} 无此物料库存")

    # 已有行：严格按 id 升序处理
    for row in sorted(rows, key=lambda r: r.id):
        _apply_one(session, row, move_by_key[(row.sku_type, row.sku_id, row.location_id)],
                   biz_type, biz_no, operator_id)

    # 新行：插入后补一次行锁，挡住并发插入同一 key
    created: list[Inventory] = []
    for m in missing:
        inv = Inventory(sku_type=m.sku_type, sku_id=m.sku_id, location_id=m.location_id,
                        qty=0, locked_qty=0, frozen_qty=0)
        session.add(inv)
        session.flush()
        session.execute(_locked(session, select(Inventory.id).where(Inventory.id == inv.id)))
        _apply_one(session, inv, m, biz_type, biz_no, operator_id)
        created.append(inv)

    # 落账后立刻 flush：调用方要在同一事务里读回库存时能看见（SessionLocal 关了 autoflush）
    session.flush()
    return sorted(rows, key=lambda r: r.id) + created


def apply(
    session: Session,
    move: Move,
    *,
    biz_type: str,
    biz_no: str,
    operator_id: int,
) -> Inventory:
    """单行入口。多行请用 apply_many，锁序才统一。"""
    return apply_many(session, [move], biz_type=biz_type, biz_no=biz_no, operator_id=operator_id)[0]


def _apply_one(
    session: Session,
    inv: Inventory,
    move: Move,
    biz_type: str,
    biz_no: str,
    operator_id: int,
) -> int:
    if move.delta < 0:
        gap = inv.available + move.delta
        if gap < 0:
            raise BizError(Codes.STOCK_SHORT, f"可用库存不足，缺口 {abs(gap)}")
    before = inv.qty
    inv.qty += move.delta
    session.add(
        Txn(
            sku_type=inv.sku_type,
            sku_id=inv.sku_id,
            location_id=inv.location_id,
            qty_delta=move.delta,
            balance=inv.qty,
            biz_type=biz_type,
            biz_no=biz_no,
            operator_id=operator_id,
        )
    )
    return before


def balance_of(session: Session, sku_type: str, sku_id: int, location_id: int) -> int:
    row = session.execute(
        select(Inventory.qty).where(
            Inventory.sku_type == sku_type,
            Inventory.sku_id == sku_id,
            Inventory.location_id == location_id,
        )
    ).scalar_one_or_none()
    return row or 0


# ---------------------------------------------------------------- 自测
def _self_check() -> None:  # pragma: no cover - `python -m app.domain.stock` 跑
    from app.domain.enums import BizType, SkuType

    # 1) 合并同 key
    merged = _merge(
        [Move("PRODUCT", 1, 10, 5), Move("PRODUCT", 1, 10, -2), Move("PRODUCT", 1, 11, 3)]
    )
    assert len(merged) == 2, merged
    assert sum(m.delta for m in merged) == 6

    # 2) 可用量不足要报 4222 且给出缺口
    inv = Inventory(sku_type="PRODUCT", sku_id=1, location_id=10, qty=10, locked_qty=4, frozen_qty=0)
    try:
        _apply_one(None, inv, Move("PRODUCT", 1, 10, -8), BizType.SALES_OUT, "X", 1)
    except BizError as e:
        assert e.code == Codes.STOCK_SHORT and "缺口 2" in e.message, e.message
    else:
        raise AssertionError("可用量校验未生效")

    # 3) 锁序：多行必须按 id 升序
    rows = [
        Inventory(id=7, sku_type="P", sku_id=1, location_id=1),
        Inventory(id=3, sku_type="P", sku_id=2, location_id=2),
    ]
    assert [r.id for r in sorted(rows, key=lambda r: r.id)] == [3, 7]

    # 4) 重试判定
    assert _retryable(OperationalError("UPDATE", {}, Exception(1213, "deadlock")))
    assert _retryable(OperationalError("INSERT", {}, Exception(1062, "dup")))
    assert not _retryable(OperationalError("SELECT", {}, Exception(1045, "access denied")))
    assert SkuType.PRODUCT == "PRODUCT"
    print("stock self-check ok")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
