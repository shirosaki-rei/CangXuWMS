# -*- coding: utf-8 -*-
"""domain/rules.py 纯规则单测：BR-008 / BR-013 / BR-025 与编号规则。"""
from __future__ import annotations

import pytest

from app.core.errors import BizError, Codes
from app.domain.rules import (
    PREFIX,
    assert_warehouse_disable_ok,
    gen_no,
    location_allows,
    location_mismatch_reason,
    location_status_after,
    mask_phone,
    next_seq_fallback,
)


@pytest.mark.parametrize("ltype,danger,temp,ok", [
    ("NORMAL", False, "NONE", True),
    ("NORMAL", True, "NONE", True),          # 危品可以放普通库位
    ("DANGEROUS", True, "NONE", True),
    ("DANGEROUS", False, "NONE", False),     # BR-013
    ("CONSTANT_TEMP", False, "COLD", True),
    ("CONSTANT_TEMP", False, "NONE", False),  # BR-013
    ("STEREO", False, "NONE", True),
])
def test_库位类型匹配(ltype, danger, temp, ok):
    assert location_allows(ltype, danger, temp) is ok


def test_不匹配时有明确原因():
    assert "危品" in (location_mismatch_reason("DANGEROUS", False, "NONE") or "")
    assert "恒温" in (location_mismatch_reason("CONSTANT_TEMP", False, "NONE") or "")
    assert location_mismatch_reason("NORMAL", False, "NONE") is None


def test_库位状态自动流转_BR008():
    assert location_status_after("IDLE", 5) == "OCCUPIED"
    assert location_status_after("OCCUPIED", 0) == "IDLE"


def test_人工设置锁定维保不被库存覆盖():
    assert location_status_after("LOCKED", 10) == "LOCKED"
    assert location_status_after("MAINTAIN", 0) == "MAINTAIN"


def test_停用仓库阻塞项_BR014():
    assert_warehouse_disable_ok([])  # 无阻塞 → 放行
    with pytest.raises(BizError) as e:
        assert_warehouse_disable_ok(["仓内仍有库存 12 件"])
    assert e.value.code == Codes.BIZ_RULE
    assert e.value.data == {"blockers": ["仓内仍有库存 12 件"]}


def test_编号流水回退取号():
    assert next_seq_fallback("PI", "20260127", None) == 1
    assert next_seq_fallback("PI", "20260127", "PI20260127007") == 8
    assert next_seq_fallback("PI", "20260127", "PI20260127999") == 1000  # 自动升 4 位
    assert next_seq_fallback("PI", "20260127", "junk") == 1


def test_前缀表完整():
    assert PREFIX["STOCKTAKE"] == "PD" and PREFIX["MOVE"] == "YK"
    assert len(PREFIX) == 10
    assert set(PREFIX.values()) == {"PI", "PR", "RT", "SG", "SO", "PL", "SL", "JY", "PD", "YK"}


def test_手机号掩码():
    assert mask_phone("13812345678") == "138****5678"
    assert mask_phone(None) is None
    assert mask_phone("123") == "123"


def test_编号格式():
    no = gen_no("PD")
    assert no.startswith("PD") and len(no) == 13, no
    assert no[2:10].isdigit() and no[10:].isdigit()
