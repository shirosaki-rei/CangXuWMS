"""纯业务规则（BR-001 ~ BR-026 中不涉及 IO 的部分）。IO 相关的放 service。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.errors import BizError, Codes
from app.core.redis import rds
from app.domain.enums import LocationStatus, LocationType, TempControl

# 单据编号前缀（PRD 10.1）
PREFIX = {
    "PRODUCT_IN": "PI",
    "PURCHASE_IN": "PR",
    "RETURN_IN": "RT",
    "GAIN_IN": "SG",
    "SALES_OUT": "SO",
    "PICK_OUT": "PL",
    "LOSS_OUT": "SL",
    "INSPECTION": "JY",
    "STOCKTAKE": "PD",
    "MOVE": "YK",
}

_SEQ_KEY = "seq:{}:{}"  # seq:<prefix>:<yyyymmdd>


def gen_no(prefix: str, *, now: datetime | None = None) -> str:
    """业务前缀 + yyyyMMdd + 日流水。单类日流水超 999 自动升 4 位（PRD 10.1）。

    ponytail: 用 Redis INCR 取号；Redis 不可用时退回 DB MAX+1，极端并发下可能跳号，
    但 uk_no 唯一索引会挡住重复（撞索引时重试一次即可）。生产 Redis 必配。
    """
    prefix = prefix.upper()
    day = (now or datetime.now(timezone.utc)).strftime("%Y%m%d")
    seq = rds.incr(_SEQ_KEY.format(prefix, day))
    if seq == 1:
        rds.expire(_SEQ_KEY.format(prefix, day), 48 * 3600)
    return f"{prefix}{day}{seq:03d}"


def next_seq_fallback(prefix: str, day: str, max_no: str | None) -> int:
    """Redis 不可用时的取号：从库里当日最大流水 +1。"""
    if not max_no or len(max_no) < len(prefix) + 8:
        return 1
    tail = max_no[len(prefix) + 8:]
    return int(tail) + 1 if tail.isdigit() else 1


def location_allows(location_type: str, is_dangerous: bool, temp_control: str) -> bool:
    """BR-013：危品库位只能放危品物料；恒温库位只能放需控温物料。"""
    if location_type == LocationType.DANGEROUS and not is_dangerous:
        return False
    if location_type == LocationType.CONSTANT_TEMP and temp_control == TempControl.NONE:
        return False
    return True


def location_mismatch_reason(location_type: str, is_dangerous: bool, temp_control: str) -> str | None:
    if location_type == LocationType.DANGEROUS and not is_dangerous:
        return "危品库位只能存放危品物料（BR-013）"
    if location_type == LocationType.CONSTANT_TEMP and temp_control == TempControl.NONE:
        return "恒温库位只能存放需要控温的物料（BR-013）"
    return None


def location_status_after(current: str, qty: int, *, manual_only: bool = True) -> str:
    """BR-008：状态自动流转，人工只能设「锁定」「维保」。

    manual_only=True 时只允许 LOCKED/MAINTAIN 之间的人工切换，其余按库存推。
    """
    if manual_only and current in (LocationStatus.LOCKED, LocationStatus.MAINTAIN):
        return current
    return LocationStatus.OCCUPIED if qty > 0 else LocationStatus.IDLE


def assert_warehouse_disable_ok(blockers: list[str]) -> None:
    """BR-014：停用仓库前校验库存为 0 且无未结单据。blockers 由 service 收集。"""
    if blockers:
        raise BizError(Codes.BIZ_RULE, "仓库存在未清项，不能停用", data={"blockers": blockers})


def mask_phone(phone: str | None) -> str | None:
    """日志与列表展示用：138****5678。"""
    if not phone or len(phone) < 7:
        return phone
    return phone[:3] + "****" + phone[-4:]


# ---------------------------------------------------------------- 自测
def _self_check() -> None:  # pragma: no cover - `python -m app.domain.rules` 跑
    assert not location_allows("DANGEROUS", False, "NONE")
    assert location_allows("DANGEROUS", True, "NONE")
    assert not location_allows("CONSTANT_TEMP", False, "NONE")
    assert location_allows("CONSTANT_TEMP", False, "COLD")
    assert location_allows("NORMAL", False, "NONE")
    assert location_mismatch_reason("DANGEROUS", False, "NONE")

    assert location_status_after("LOCKED", 10) == "LOCKED", "人工锁定不被库存覆盖"
    assert location_status_after("MAINTAIN", 0) == "MAINTAIN"
    assert location_status_after("IDLE", 5) == "OCCUPIED"
    assert location_status_after("OCCUPIED", 0) == "IDLE"

    assert next_seq_fallback("PI", "20260127", None) == 1
    assert next_seq_fallback("PI", "20260127", "PI20260127007") == 8
    assert next_seq_fallback("PI", "20260127", "garbage") == 1

    assert mask_phone("13812345678") == "138****5678"
    assert mask_phone(None) is None
    assert mask_phone("123") == "123"

    assert PREFIX["STOCKTAKE"] == "PD" and len(PREFIX) == 10
    print("rules self-check ok")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
