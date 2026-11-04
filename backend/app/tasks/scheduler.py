"""定时任务进程（T-05-4）：采纳率复核、每日对账、日志清理、超期单据清理、AI 周报。

单实例运行（compose 里 worker 只起一个），避免任务重复执行。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import delete, func, select

from app.core.db import SessionLocal
from app.core.logging import get_logger, setup_logging
from app.domain.models import (
    SysConfig,
    AiFeedback,
    AiSuggestion,
    InboundOrder,
    NlQueryLog,
    OpLog,
    OutboundOrder,
    ReconcileDiff,
)
from app.tasks import backup, reconcile

log = get_logger("wms.tasks")

RETENTION_DAYS = 180          # BR-018：校验结果与建议记录留存 ≥180 天
STALE_ORDER_DAYS = 30         # 超期未结单据
ADOPTION_OFFLINE_RATIO = 0.30  # BR-022
ADOPTION_WEEKS = 2


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def reconcile_daily() -> None:
    try:
        with SessionLocal() as s:
            reconcile.run(s)
    except Exception:  # noqa: BLE001
        log.exception("daily reconcile failed")


def backup_daily() -> None:
    try:
        backup.run()
    except Exception:  # noqa: BLE001
        log.exception("daily backup failed")


def cleanup_old_records() -> None:
    """180 天前的建议/反馈/问数日志/幂等日志。"""
    cutoff = _now() - timedelta(days=RETENTION_DAYS)
    with SessionLocal() as s:
        for model, col in ((AiFeedback, AiFeedback.created_at),
                           (AiSuggestion, AiSuggestion.created_at),
                           (NlQueryLog, NlQueryLog.created_at),
                           (OpLog, OpLog.created_at)):
            n = s.execute(delete(model).where(col < cutoff)).rowcount
            if n:
                log.info("cleanup %s: %d 行", model.__tablename__, n)
        s.commit()


def close_stale_orders() -> None:
    """超期未结单据只告警不自动作废——作废需要人给原因（BR-011）。"""
    cutoff = _now() - timedelta(days=STALE_ORDER_DAYS)
    with SessionLocal() as s:
        for model in (InboundOrder, OutboundOrder):
            n = s.execute(
                select(func.count()).select_from(model).where(
                    model.status.in_(("PENDING", "PARTIAL")), model.created_at < cutoff)
            ).scalar()
            if n:
                log.error("%s 有 %d 张单据超过 %d 天未结，请人工处理",
                          model.__tablename__, n, STALE_ORDER_DAYS)


def adoption_review() -> None:
    """BR-022：某类建议连续 2 周采纳率 < 30% → 记 ERROR（自动下线需人工确认开关）。"""
    since = _now() - timedelta(weeks=ADOPTION_WEEKS)
    with SessionLocal() as s:
        rows = s.execute(
            select(AiSuggestion.type, AiFeedback.action, func.count())
            .join(AiSuggestion, AiSuggestion.id == AiFeedback.suggestion_id)
            .where(AiSuggestion.created_at >= since)
            .group_by(AiSuggestion.type, AiFeedback.action)
        ).all()
    stats: dict[str, dict[str, int]] = {}
    for kind, action, n in rows:
        stats.setdefault(kind, {})[action] = int(n)

    for kind, acts in stats.items():
        acc, rej = acts.get("ACCEPT", 0), acts.get("REJECT", 0)
        base = acc + rej
        if base < 10:
            continue  # 样本太少不下结论
        rate = acc / base
        if rate < ADOPTION_OFFLINE_RATIO:
            _set_offline(kind, True)
            log.error("建议 %s 近 %d 周采纳率 %.0f%% < %.0f%%，已自动下线（BR-022）",
                      kind, ADOPTION_WEEKS, rate * 100, ADOPTION_OFFLINE_RATIO * 100)
        else:
            log.info("建议 %s 采纳率 %.0f%%", kind, rate * 100)


OFFLINE_KEY = {"LOCATION": "ai_location_offline", "PATH": "ai_path_offline",
               "CHECK": "ai_check_offline"}


def _set_offline(kind: str, value: bool) -> None:
    """把自动下线开关写进 sys_config，AI 服务读它决定是否继续给建议。"""
    key = OFFLINE_KEY.get(kind)
    if not key:
        return
    with SessionLocal() as s:
        row = s.execute(select(SysConfig).where(
            SysConfig.cfg_key == key, SysConfig.scope == "GLOBAL",
            SysConfig.scope_id.is_(None))).scalars().first()
        val = "true" if value else "false"
        if row is None:
            s.add(SysConfig(cfg_key=key, cfg_value=val, value_type="BOOL",
                            scope="GLOBAL", remark="BR-022 自动下线开关"))
        else:
            row.cfg_value = val
        s.commit()


def weekly_report() -> None:
    """AI 周报：把本周建议与采纳率汇总成一行日志（接入邮件/IM 由运维手册决定）。"""
    since = _now() - timedelta(weeks=1)
    with SessionLocal() as s:
        total = s.execute(select(func.count()).select_from(AiSuggestion).where(
            AiSuggestion.created_at >= since)).scalar() or 0
        acc = s.execute(
            select(func.count()).select_from(AiFeedback)
            .where(AiFeedback.created_at >= since, AiFeedback.action == "ACCEPT")
        ).scalar() or 0
    log.info("AI 周报：本周建议 %d 条，采纳 %d 条", total, acc)


def open_diff_alert() -> None:
    with SessionLocal() as s:
        n = s.execute(select(func.count()).select_from(ReconcileDiff).where(
            ReconcileDiff.resolved.is_(False))).scalar() or 0
    if n:
        log.error("对账差异未解决 %d 条，请到 reconcile_diff 处理", n)


def main() -> None:
    setup_logging()  # worker 不做 FastAPI 启动，必须自己挂 handler，否则 INFO 全丢
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(reconcile_daily, "cron", hour=2, minute=0, id="reconcile")
    sched.add_job(close_stale_orders, "cron", hour=2, minute=10, id="stale")
    sched.add_job(open_diff_alert, "cron", hour=2, minute=20, id="diff-alert")
    sched.add_job(backup_daily, "cron", hour=3, minute=0, id="backup")
    sched.add_job(cleanup_old_records, "cron", hour=3, minute=30, id="cleanup")
    sched.add_job(adoption_review, "cron", day_of_week="mon", hour=9, minute=0,
                  id="adoption")
    sched.add_job(weekly_report, "cron", day_of_week="mon", hour=9, minute=10,
                  id="weekly-report")
    log.info("scheduler started")
    sched.start()


if __name__ == "__main__":  # pragma: no cover
    main()
