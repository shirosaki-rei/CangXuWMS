"""权限矩阵（PRD 3.2）。前后端共用：后端做鉴权，前端权限矩阵页直接渲染这张表。"""
from __future__ import annotations

# 功能键 -> 允许的角色集合
MATRIX: dict[str, frozenset[str]] = {
    "inventory:view": frozenset({"KEEPER", "INSPECTOR", "SUPERVISOR", "ADMIN"}),
    "inbound:exec": frozenset({"KEEPER", "SUPERVISOR"}),
    "inbound:submit": frozenset({"KEEPER", "SUPERVISOR", "ADMIN"}),
    "inbound:void": frozenset({"SUPERVISOR", "ADMIN"}),
    "inspection:judge": frozenset({"INSPECTOR"}),
    "inspection:review": frozenset({"SUPERVISOR"}),
    "outbound:exec": frozenset({"KEEPER", "SUPERVISOR"}),
    "outbound:submit": frozenset({"KEEPER", "SUPERVISOR", "ADMIN"}),
    "outbound:void": frozenset({"SUPERVISOR", "ADMIN"}),
    "stocktake:manage": frozenset({"SUPERVISOR"}),
    # 供应商档案（含超收阈值覆盖 BR-023）：主管与管理员
    "supplier:manage": frozenset({"SUPERVISOR", "ADMIN"}),
    "move:create": frozenset({"KEEPER", "SUPERVISOR"}),
    "basedata:view": frozenset({"KEEPER", "INSPECTOR", "SUPERVISOR", "ADMIN"}),
    "basedata:manage": frozenset({"ADMIN"}),
    "ai:accept": frozenset({"KEEPER", "SUPERVISOR", "ADMIN"}),
    "ai:query": frozenset({"KEEPER", "INSPECTOR", "SUPERVISOR", "ADMIN"}),
    "ai:dashboard": frozenset({"SUPERVISOR", "ADMIN"}),
    "system:manage": frozenset({"ADMIN"}),
}

# 这些功能受「可见仓库」数据权限约束（PRD 3.2 数据权限段）
WAREHOUSE_SCOPED: frozenset[str] = frozenset({"ai:query"})

# 见全部仓库的角色；其余角色只可见 user_warehouse 里分配的仓库
ALL_WAREHOUSE_ROLES: frozenset[str] = frozenset({"SUPERVISOR", "ADMIN", "INTEGRATION"})

ROLE_LABELS = {
    "KEEPER": "仓管员",
    "INSPECTOR": "检验员",
    "SUPERVISOR": "仓库主管",
    "ADMIN": "系统管理员",
    "INTEGRATION": "集成账号",
}

# 前端权限矩阵页渲染用：与 PRD 3.2 的 14 行一一对应
MATRIX_ROWS: list[dict] = [
    {"key": "inventory:view", "name": "库存查询 / 流水查询", "KEEPER": "✅", "INSPECTOR": "✅",
     "SUPERVISOR": "✅", "ADMIN": "✅"},
    {"key": "inbound:exec", "name": "入库单执行（扫码收货）", "KEEPER": "✅", "INSPECTOR": "—",
     "SUPERVISOR": "✅", "ADMIN": "—"},
    {"key": "inbound:submit", "name": "入库单提交", "KEEPER": "✅", "INSPECTOR": "—",
     "SUPERVISOR": "✅", "ADMIN": "✅"},
    {"key": "inbound:void", "name": "入库单作废", "KEEPER": "—", "INSPECTOR": "—",
     "SUPERVISOR": "✅", "ADMIN": "✅"},
    {"key": "inspection:judge", "name": "来料检验判定", "KEEPER": "—", "INSPECTOR": "✅",
     "SUPERVISOR": "—", "ADMIN": "—"},
    {"key": "inspection:review", "name": "检验单复核", "KEEPER": "—", "INSPECTOR": "—",
     "SUPERVISOR": "✅", "ADMIN": "—"},
    {"key": "outbound:exec", "name": "出库单执行（拣货发货）", "KEEPER": "✅", "INSPECTOR": "—",
     "SUPERVISOR": "✅", "ADMIN": "—"},
    {"key": "outbound:submit", "name": "出库单提交", "KEEPER": "✅", "INSPECTOR": "—",
     "SUPERVISOR": "✅", "ADMIN": "✅"},
    {"key": "outbound:void", "name": "出库单作废", "KEEPER": "—", "INSPECTOR": "—",
     "SUPERVISOR": "✅", "ADMIN": "✅"},
    {"key": "stocktake:manage", "name": "盘点单创建 / 盈亏确认", "KEEPER": "—", "INSPECTOR": "—",
     "SUPERVISOR": "✅", "ADMIN": "—"},
    {"key": "move:create", "name": "移位单创建", "KEEPER": "✅", "INSPECTOR": "—",
     "SUPERVISOR": "✅", "ADMIN": "—"},
    {"key": "basedata:view", "name": "仓库 / 库位 / 条码查看", "KEEPER": "✅", "INSPECTOR": "✅",
     "SUPERVISOR": "✅", "ADMIN": "✅"},
    {"key": "basedata:manage", "name": "仓库 / 库位 / 条码维护", "KEEPER": "—", "INSPECTOR": "—",
     "SUPERVISOR": "—", "ADMIN": "✅"},
    {"key": "ai:accept", "name": "AI 建议采纳", "KEEPER": "✅", "INSPECTOR": "—",
     "SUPERVISOR": "✅", "ADMIN": "✅"},
    {"key": "ai:query", "name": "智能问数（X01）", "KEEPER": "仅本仓", "INSPECTOR": "仅本仓",
     "SUPERVISOR": "全部仓库", "ADMIN": "全部仓库"},
    {"key": "ai:dashboard", "name": "AI 效果看板（X05）", "KEEPER": "—", "INSPECTOR": "—",
     "SUPERVISOR": "✅", "ADMIN": "✅"},
    {"key": "system:manage", "name": "权限与账号管理", "KEEPER": "—", "INSPECTOR": "—",
     "SUPERVISOR": "—", "ADMIN": "✅"},
]


def allows(role: str, perm: str) -> bool:
    return role in MATRIX.get(perm, frozenset())


def is_warehouse_scoped(perm: str) -> bool:
    return perm in WAREHOUSE_SCOPED
