"""问数编排（接口 55 / X01）。

链路：意图解析 → 语义层渲染 SQL → guard 白名单 → 只读连接执行 → LLM 组织话术（可降级）。
未命中模板时**不编 SQL**，直接告诉用户「该口径暂无数据」（ADR-006）。
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai import llm_gateway
from app.ai.nl_query import guard, intent, semantics
from app.core.errors import BizError, Codes
from app.domain.models import NlQueryLog
from app.service.admin_service import get_config

MAX_ROWS = guard.MAX_ROWS


def _trace() -> str:
    return uuid.uuid4().hex


def _log(db: Session, *, trace_id: str, user_id: int, question: str, metric: str | None,
         sql: str | None, rows: int, elapsed: int, rejected: bool) -> None:
    db.add(NlQueryLog(trace_id=trace_id[:32], user_id=user_id, question=question[:255],
                      intent=metric, metric=metric, generated_sql=sql,
                      row_count=rows, elapsed_ms=elapsed, rejected=rejected))
    db.commit()


def _enabled(db: Session) -> bool:
    return str(get_config(db, "query_enabled", "true")).lower() in ("true", "1", "yes", "on")


def ask(ro: Session, db: Session, *, question: str, user_id: int,
        warehouse_ids: list[int] | None) -> dict:
    trace_id = _trace()
    started = time.perf_counter()

    if not _enabled(db):
        raise BizError(Codes.BIZ_RULE, "问数功能已关闭", data={"query_enabled": False})

    parsed = intent.parse(question)
    metric = semantics.BY_KEY.get(parsed["metric"] or "")

    # 未命中模板：不生成 SQL，也不让 LLM 现编（ADR-006）
    if metric is None:
        elapsed = int((time.perf_counter() - started) * 1000)
        _log(db, trace_id=trace_id, user_id=user_id, question=question, metric=None,
             sql=None, rows=0, elapsed=elapsed, rejected=False)
        return {
            "conclusion": "该口径暂无数据，已记录待补充模板",
            "table": {"columns": [], "rows": []},
            "caliber": None,
            "metric": None,
            "sql": None,
            "row_count": 0,
            "updated_at": _now_iso(),
            "degraded": False,
            "trace_id": trace_id,
        }

    p = semantics.Params(
        start=parsed["params"]["start"], end=parsed["params"]["end"],
        sku_code=parsed["params"]["sku_code"],
        warehouse_ids=warehouse_ids,
    )
    rendered = metric.builder(p)
    sql = guard.enforce_limit(rendered.sql, MAX_ROWS)

    ok, reason = guard.validate(sql)
    if not ok:
        elapsed = int((time.perf_counter() - started) * 1000)
        _log(db, trace_id=trace_id, user_id=user_id, question=question,
             metric=metric.key, sql=sql, rows=0, elapsed=elapsed, rejected=True)
        raise BizError(Codes.BIZ_RULE, f"查询被安全策略拒绝：{reason}")

    try:
        result = ro.execute(text(sql), {**rendered.binds})
        raw = result.fetchall()
        columns = rendered.columns
    except Exception as e:  # noqa: BLE001
        elapsed = int((time.perf_counter() - started) * 1000)
        _log(db, trace_id=trace_id, user_id=user_id, question=question,
             metric=metric.key, sql=sql, rows=0, elapsed=elapsed, rejected=True)
        raise BizError(Codes.SERVER_ERROR, f"查询执行失败：{type(e).__name__}") from e

    rows = [[_cell(c) for c in r] for r in raw[:MAX_ROWS]]
    elapsed = int((time.perf_counter() - started) * 1000)

    total = sum(r[1] for r in rows if len(r) > 1 and isinstance(r[1], (int, float))) \
        if metric.key in ("outbound_qty", "inbound_qty") else None
    conclusion = _conclusion(metric, rows, total, rendered.unit)

    # LLM 只负责把结论说得自然；不可用时直接用模板文案
    degraded = False
    if llm_gateway.settings.llm_base_url:
        res = llm_gateway.ask(
            f"用一句中文总结这组数据：{conclusion}", user_id=user_id, fallback=conclusion)
        conclusion = res.text or conclusion
        degraded = res.degraded

    _log(db, trace_id=trace_id, user_id=user_id, question=question, metric=metric.key,
         sql=sql, rows=len(rows), elapsed=elapsed, rejected=False)

    return {
        "conclusion": conclusion,
        "table": {"columns": columns, "rows": rows},
        "caliber": rendered.caliber,
        "metric": metric.key,
        "sql": sql,
        "row_count": len(rows),
        "updated_at": _now_iso(),
        "degraded": degraded,
        "trace_id": trace_id,
    }


def _conclusion(metric, rows: list, total, unit: str) -> str:
    label = semantics.BY_KEY[metric.key].label
    if not rows:
        return f"该时间段内没有{label}记录"
    if total is not None:
        return f"所选时间段内{label}合计 {int(total)} {unit}"
    return f"共 {len(rows)} 条{label}记录"


def _cell(v):
    from decimal import Decimal

    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
