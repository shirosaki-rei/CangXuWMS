"""提交前校验引擎（X04 / 接口 54 / PRD 8.3 + 架构 8.4）。

11 条规则全部注册；(单据类型, 规则号) → 规则函数。
规则签名统一 (ctx) -> list[CheckResult]，无 IO、无副作用，靠 unit test 保证。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

# 阈值（PRD 8.3 / 6.9，可由 sys_config 覆盖）
DEFAULT_DEVIATION = Decimal("0.10")   # R1
DEFAULT_OVER_RECEIVE = Decimal("0.05")  # R4
DEFAULT_DIFF_RATE = Decimal("0.05")     # R9
SUPPLIER_RISK_FAIL_RATE = Decimal("0.20")  # R7
DUP_WINDOW_HOURS = 30                   # R2 实际按「本单内重复」判断，24h 口径见注释


@dataclass
class CheckResult:
    rule: str
    level: str            # PASS / WARN / BLOCK / LOG / SKIP / TIMEOUT
    title: str
    detail: str | None = None
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {"rule": self.rule, "level": self.level, "title": self.title}
        if self.detail:
            d["detail"] = self.detail
        if self.actions:
            d["actions"] = self.actions
        return d


@dataclass
class CheckContext:
    order_type: str                    # INBOUND / OUTBOUND / STOCKTAKE
    order_no: str = ""
    plan_qty: int = 0
    actual_qty: int = 0
    deviation_ratio: Decimal = DEFAULT_DEVIATION
    over_receive_ratio: Decimal = DEFAULT_OVER_RECEIVE
    diff_rate_ratio: Decimal = DEFAULT_DIFF_RATE

    # 明细
    items: list[dict] = field(default_factory=list)   # {box_code, sn, location_type, ...}
    duplicate_codes: list[str] = field(default_factory=list)
    mismatch_locations: list[str] = field(default_factory=list)

    # 出库
    available: int | None = None

    # 供应商
    supplier_fail_rate: Decimal | None = None

    # 盘点
    total: int = 0
    done: int = 0
    diff_items: int = 0
    locked_events: int = 0
    blank_items: int = 0

    # 时间
    now: datetime | None = None
    recent_submits_1h: int = 0


def _pct(x: Decimal) -> str:
    return f"{x * 100:.0f}%"


# ---------------------------------------------------------------- 规则
def r1_qty_deviation(ctx: CheckContext) -> CheckResult:
    if not ctx.plan_qty:
        return CheckResult("R1", "SKIP", "数量偏差校验", "计划数量为 0，不适用")
    diff = ctx.actual_qty - ctx.plan_qty
    ratio = Decimal(diff) / Decimal(ctx.plan_qty)
    if abs(ratio) <= ctx.deviation_ratio:
        return CheckResult("R1", "PASS", "数量偏差在阈值内",
                           f"实收 {ctx.actual_qty}，计划 {ctx.plan_qty}，偏差 {ratio * 100:+.0f}%")
    return CheckResult(
        "R1", "WARN", f"数量偏差 {ratio * 100:+.0f}%",
        f"实际 {ctx.actual_qty}，计划 {ctx.plan_qty}，偏差 {ratio * 100:+.0f}%，"
        f"阈值 {_pct(ctx.deviation_ratio)}",
        ["VIEW_DIFF", "FILL_REASON"],
    )


def r2_duplicate_scan(ctx: CheckContext) -> CheckResult:
    if not ctx.items:
        return CheckResult("R2", "SKIP", "重复扫码校验", "没有明细")
    if ctx.duplicate_codes:
        return CheckResult("R2", "WARN", f"发现 {len(ctx.duplicate_codes)} 处重复扫码",
                           "重复：" + "、".join(ctx.duplicate_codes[:5]), ["VIEW_DUPLICATE"])
    return CheckResult("R2", "PASS", "无重复扫码")


def r3_location_type(ctx: CheckContext) -> CheckResult:
    if not ctx.items:
        return CheckResult("R3", "SKIP", "库位类型校验", "没有明细")
    if ctx.mismatch_locations:
        return CheckResult("R3", "BLOCK", f"{len(ctx.mismatch_locations)} 个库位类型不匹配",
                           "不匹配：" + "、".join(ctx.mismatch_locations[:5]), ["CHANGE_LOCATION"])
    return CheckResult("R3", "PASS", "库位与物料类型匹配")


def r4_over_receive(ctx: CheckContext) -> CheckResult:
    if ctx.order_type != "INBOUND":
        return CheckResult("R4", "SKIP", "超收比例", "不适用于非入库单，跳过且不计入通过数")
    if ctx.actual_qty <= ctx.plan_qty:
        return CheckResult("R4", "PASS", "超收比例 0%")
    over = Decimal(ctx.actual_qty - ctx.plan_qty) / Decimal(max(1, ctx.plan_qty))
    if over <= ctx.over_receive_ratio:
        return CheckResult("R4", "PASS", f"超收 {over * 100:.0f}%，在阈值内",
                           f"阈值 {_pct(ctx.over_receive_ratio)}")
    return CheckResult("R4", "WARN", f"超收 {over * 100:.0f}%，超过阈值",
                       f"阈值 {_pct(ctx.over_receive_ratio)}，需转主管审批", ["CALL_SUPERVISOR"])


def r5_stock_available(ctx: CheckContext) -> CheckResult:
    if ctx.order_type == "INBOUND":
        return CheckResult("R5", "SKIP", "可用库存校验", "不适用于入库单，跳过且不计入通过数")
    if ctx.available is None:
        return CheckResult("R5", "SKIP", "可用库存校验", "缺少库存数据")
    if ctx.actual_qty > ctx.available:
        return CheckResult("R5", "BLOCK", f"可用库存不足，缺 {ctx.actual_qty - ctx.available}",
                           f"需求 {ctx.actual_qty}，可用 {ctx.available}", ["SPLIT_ORDER"])
    return CheckResult("R5", "PASS", "可用库存充足",
                       f"需求 {ctx.actual_qty}，可用 {ctx.available}")


def r6_time_anomaly(ctx: CheckContext) -> CheckResult:
    """记录级，不计入计数（架构 8.4）。"""
    now = ctx.now or datetime.now()
    off_hours = now.hour < 7 or now.hour >= 21
    burst = ctx.recent_submits_1h > 50
    if off_hours and burst:
        return CheckResult("R6", "LOG", f"非工作时段批量提交 {ctx.recent_submits_1h} 单/小时",
                           f"{now:%H:%M}，仅审计")
    return CheckResult("R6", "PASS", "时间正常")


def r7_supplier_risk(ctx: CheckContext) -> CheckResult:
    if ctx.order_type != "INBOUND":
        return CheckResult("R7", "SKIP", "供应商历史风险", "不适用于非入库单")
    if ctx.supplier_fail_rate is None:
        return CheckResult("R7", "SKIP", "供应商历史风险", "缺少供应商质量数据")
    if ctx.supplier_fail_rate > SUPPLIER_RISK_FAIL_RATE:
        return CheckResult("R7", "WARN", f"供应商近 3 批不合格率 {_pct(ctx.supplier_fail_rate)}",
                           f"高于 {_pct(SUPPLIER_RISK_FAIL_RATE)}，建议全检", ["FULL_INSPECTION"])
    return CheckResult("R7", "PASS", "供应商质量正常",
                       f"近 3 批不合格率 {_pct(ctx.supplier_fail_rate)}")


def r8_unchecked_locations(ctx: CheckContext) -> CheckResult:
    undone = ctx.total - ctx.done
    if undone > 0:
        return CheckResult("R8", "WARN", f"{undone} 个条目未盘",
                           "未盘按账面结转，或继续盘点", ["CONTINUE_COUNT"])
    return CheckResult("R8", "PASS", "全部盘完")


def r9_diff_rate(ctx: CheckContext) -> CheckResult:
    if not ctx.total:
        return CheckResult("R9", "SKIP", "差异率校验", "没有应盘条目")
    rate = Decimal(ctx.diff_items) / Decimal(ctx.total)
    if rate > ctx.diff_rate_ratio:
        return CheckResult("R9", "WARN", f"差异率 {rate * 100:.1f}%，超过阈值",
                           f"差异 {ctx.diff_items} / 应盘 {ctx.total}，阈值 {_pct(ctx.diff_rate_ratio)}",
                           ["CALL_SUPERVISOR"])
    return CheckResult("R9", "PASS", f"差异率 {rate * 100:.1f}%")


def r10_location_locked(ctx: CheckContext) -> CheckResult:
    if ctx.locked_events > 0:
        return CheckResult("R10", "WARN", "盘点期间有出入库事务",
                           f"{ctx.locked_events} 笔，账面数可能失真", ["REVIEW_TXN"])
    return CheckResult("R10", "PASS", "盘点期间无出入库事务")


def r11_order_integrity(ctx: CheckContext) -> CheckResult:
    if ctx.blank_items > 0:
        return CheckResult("R11", "WARN", f"{ctx.blank_items} 条已盘记录有空值或重复",
                           "补录后重新校验", ["FIX_BLANK"])
    return CheckResult("R11", "PASS", "单据完整")


# (单据类型, 规则号) → 规则函数；'*' 表示全局
RULES: dict[tuple[str, str], callable] = {
    ("INBOUND", "R1"): r1_qty_deviation,
    ("INBOUND", "R2"): r2_duplicate_scan,
    ("INBOUND", "R3"): r3_location_type,
    ("INBOUND", "R4"): r4_over_receive,
    ("INBOUND", "R5"): r5_stock_available,   # 入库不校验库存，但要在结果里显式标 SKIP（接口 3.6）
    ("INBOUND", "R7"): r7_supplier_risk,
    ("OUTBOUND", "R1"): r1_qty_deviation,
    ("OUTBOUND", "R2"): r2_duplicate_scan,
    ("OUTBOUND", "R3"): r3_location_type,
    ("OUTBOUND", "R4"): r4_over_receive,     # 出库无超收概念，同样显式 SKIP
    ("OUTBOUND", "R5"): r5_stock_available,
    ("STOCKTAKE", "R8"): r8_unchecked_locations,
    ("STOCKTAKE", "R9"): r9_diff_rate,
    ("STOCKTAKE", "R10"): r10_location_locked,
    ("STOCKTAKE", "R11"): r11_order_integrity,
    ("*", "R6"): r6_time_anomaly,
}

_ALL_TYPES = ("INBOUND", "OUTBOUND", "STOCKTAKE")


def run(ctx: CheckContext) -> list[CheckResult]:
    """顺序执行（规则都是纯函数、微秒级，没有必要真开线程池）。"""
    out: list[CheckResult] = []
    for (t, rule), fn in RULES.items():
        if t not in (ctx.order_type, "*"):
            continue
        try:
            out.append(fn(ctx))
        except Exception as e:  # noqa: BLE001
            out.append(CheckResult(rule, "TIMEOUT", "规则执行异常",
                                   f"{type(e).__name__}: {e}"))
    out.sort(key=lambda r: (r.rule != "R6", r.rule))
    return out


def summary(results: list[CheckResult]) -> dict:
    """R6 是记录级，不计入通过/预警数（架构 8.4）。"""
    s = {"pass": 0, "warn": 0, "block": 0, "timeout": 0, "skipped": 0}
    for r in results:
        if r.rule == "R6" or r.level == "LOG":
            continue
        if r.level == "PASS":
            s["pass"] += 1
        elif r.level == "WARN":
            s["warn"] += 1
        elif r.level == "BLOCK":
            s["block"] += 1
        elif r.level == "TIMEOUT":
            s["timeout"] += 1
        elif r.level == "SKIP":
            s["skipped"] += 1
    return s
