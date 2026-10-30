# -*- coding: utf-8 -*-
"""权限矩阵与数据权限纯逻辑测试（T-00-5 交付物）。"""
from __future__ import annotations

import pytest

from app.core.permissions import (
    ALL_WAREHOUSE_ROLES,
    MATRIX,
    MATRIX_ROWS,
    ROLE_LABELS,
    WAREHOUSE_SCOPED,
    allows,
    is_warehouse_scoped,
)
from app.domain.enums import Role


def test_五种角色都有标签():
    assert set(ROLE_LABELS) == {str(r) for r in Role}


@pytest.mark.parametrize("role,perm,expected", [
    ("ADMIN", "system:manage", True),
    ("SUPERVISOR", "system:manage", False),
    ("KEEPER", "inbound:exec", True),
    ("INSPECTOR", "inbound:exec", False),
    ("INSPECTOR", "inspection:judge", True),
    ("SUPERVISOR", "inspection:review", True),
    ("KEEPER", "inbound:void", False),      # 只有主管/管理员能作废
    ("SUPERVISOR", "inbound:void", True),
    ("KEEPER", "basedata:manage", False),   # 基础资料仅管理员可写
    ("ADMIN", "basedata:manage", True),
    ("KEEPER", "basedata:view", True),      # 但可读
    ("KEEPER", "ai:query", True),
    ("INSPECTOR", "ai:query", True),
    ("KEEPER", "ai:dashboard", False),
    ("SUPERVISOR", "ai:dashboard", True),
    ("KEEPER", "stocktake:manage", False),
    ("SUPERVISOR", "stocktake:manage", True),
    ("INTEGRATION", "system:manage", False),  # 集成账号无 UI 权限
    ("INTEGRATION", "inventory:view", False),
])
def test_角色权限判定(role, perm, expected):
    assert allows(role, perm) is expected


def test_未知角色一律拒绝():
    assert not allows("GHOST", "inventory:view")
    assert not allows("", "system:manage")


def test_见全部仓库的角色():
    assert ALL_WAREHOUSE_ROLES == {"SUPERVISOR", "ADMIN", "INTEGRATION"}
    assert "KEEPER" not in ALL_WAREHOUSE_ROLES
    assert "INSPECTOR" not in ALL_WAREHOUSE_ROLES


def test_问数受数据权限约束():
    assert is_warehouse_scoped("ai:query")
    assert not is_warehouse_scoped("inventory:view")


def test_矩阵行与MATRIX不矛盾():
    """MATRIX_ROWS 是给前端渲染的，必须与 MATRIX 一致（PRD 3.2）。"""
    assert len(MATRIX_ROWS) == 17
    for row in MATRIX_ROWS:
        key = row["key"]
        assert key in MATRIX, key
        for role in ("KEEPER", "INSPECTOR", "SUPERVISOR", "ADMIN"):
            cell = row[role]
            has = role in MATRIX[key]
            if cell == "✅":
                assert has, f"{key}/{role} 标了 ✅ 但 MATRIX 没有"
            elif cell == "—":
                assert not has, f"{key}/{role} 标了 — 但 MATRIX 有"
            else:  # 仅本仓 / 全部仓库
                assert has, f"{key}/{role} 标了 {cell} 但 MATRIX 没有"


def test_矩阵行覆盖PRD的14行功能():
    names = [r["name"] for r in MATRIX_ROWS]
    for kw in ("库存查询", "入库单执行", "入库单提交", "入库单作废", "来料检验判定",
               "检验单复核", "出库单执行", "出库单提交", "出库单作废",
               "盘点单创建", "移位单创建", "条码", "AI 建议采纳", "智能问数",
               "AI 效果看板", "权限与账号管理"):
        assert any(kw in n for n in names), kw
