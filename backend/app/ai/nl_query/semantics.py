"""指标语义层（架构 8.6 / ADR-006）。

每个指标 = 一段固定的 SQL 模板 + 口径说明。LLM 只选指标和填参数，不写 SQL，
所以同一个问题永远得到同一条 SQL、同一份结果（AC-AI-09）。

用 Python dict 而不是 metrics.yaml：项目没有 yaml 依赖，而这里的模板需要
按参数拼条件（可选 SKU、可选仓库、时间区间），写成函数比字符串模板更直白。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class Params:
    start: datetime
    end: datetime
    sku_code: str | None = None
    sku_type: str | None = None          # PRODUCT / MATERIAL
    warehouse_ids: list[int] | None = None  # None = 不限（主管/管理员）

    def binds(self) -> dict:
        return {"start": self.start, "end": self.end}


@dataclass
class Rendered:
    sql: str
    binds: dict
    columns: list[str]
    caliber: str
    label: str
    unit: str = ""


def _wh_clause(col: str, p: Params) -> tuple[str, dict]:
    """数据权限：非 None 时强制注入可见仓库，前端无从绕过（AC-AI-12）。"""
    if p.warehouse_ids is None:
        return "", {}
    if not p.warehouse_ids:
        return " AND 1=0", {}
    return f" AND {col} IN ({','.join(str(int(i)) for i in p.warehouse_ids)})", {}


def outbound_qty(p: Params) -> Rendered:
    wh, b = _wh_clause("l.warehouse_id", p)
    b = {**p.binds(), **b}
    sku = ""
    if p.sku_code:
        t = "product" if (p.sku_type or "PRODUCT") == "PRODUCT" else "material"
        sku = f" AND t.sku_id = (SELECT id FROM {t} WHERE code = :sku_code)"
        b["sku_code"] = p.sku_code
    sql = f"""
        SELECT DATE(t.created_at) AS d,
               SUM(-t.qty_delta) AS qty,
               COUNT(DISTINCT t.biz_no) AS docs
        FROM txn t
        JOIN location l ON l.id = t.location_id
        WHERE t.biz_type IN ('SALES_OUT','PICK_OUT','LOSS_OUT')
          AND t.created_at BETWEEN :start AND :end{sku}{wh}
        GROUP BY DATE(t.created_at)
        ORDER BY d
        LIMIT 5000
    """
    return Rendered(sql.strip(), b, ["日期", "出库数量", "单据数"],
                    "按已出库单据的实际出库数量汇总，不含待出库", "出库数量", "件")


def inbound_qty(p: Params) -> Rendered:
    wh, b = _wh_clause("l.warehouse_id", p)
    b = {**p.binds(), **b}
    sku = ""
    if p.sku_code:
        t = "product" if (p.sku_type or "PRODUCT") == "PRODUCT" else "material"
        sku = f" AND t.sku_id = (SELECT id FROM {t} WHERE code = :sku_code)"
        b["sku_code"] = p.sku_code
    sql = f"""
        SELECT DATE(t.created_at) AS d,
               SUM(t.qty_delta) AS qty,
               COUNT(DISTINCT t.biz_no) AS docs
        FROM txn t
        JOIN location l ON l.id = t.location_id
        WHERE t.biz_type IN ('PURCHASE_IN','PRODUCT_IN','RETURN_IN','GAIN_IN','STOCKTAKE_IN')
          AND t.created_at BETWEEN :start AND :end{sku}{wh}
        GROUP BY DATE(t.created_at)
        ORDER BY d
        LIMIT 5000
    """
    return Rendered(sql.strip(), b, ["日期", "入库数量", "单据数"],
                    "按已入库单据的实际入库数量汇总", "入库数量", "件")


def inventory_qty(p: Params) -> Rendered:
    """当前库存（不限时间）。SKU 不传时列出 Top 50。"""
    wh, b = _wh_clause("l.warehouse_id", p)
    b = {**p.binds(), **b}
    if p.sku_code:
        t = "product" if (p.sku_type or "PRODUCT") == "PRODUCT" else "material"
        sql = f"""
            SELECT m.code, m.name, SUM(i.qty) AS qty,
                   SUM(i.qty - i.locked_qty - i.frozen_qty) AS available
            FROM inventory i
            JOIN location l ON l.id = i.location_id
            JOIN {t} m ON m.id = i.sku_id
            WHERE i.sku_type = :sku_type AND m.code = :sku_code{wh}
            GROUP BY m.code, m.name
            LIMIT 5000
        """
        b.update({"sku_code": p.sku_code, "sku_type": (p.sku_type or "PRODUCT")})
        return Rendered(sql.strip(), b, ["编码", "名称", "总库存", "可用"],
                        "物理库存含锁定；可用 = 总库存 − 锁库 − 冻结", "库存", "件")

    sql = f"""
        SELECT m.code, m.name, SUM(i.qty) AS qty
        FROM inventory i
        JOIN location l ON l.id = i.location_id
        JOIN material m ON m.id = i.sku_id
        WHERE i.sku_type = 'MATERIAL' AND i.qty > 0{wh}
        GROUP BY m.code, m.name
        ORDER BY qty DESC
        LIMIT 50
    """
    return Rendered(sql.strip(), b, ["编码", "名称", "库存"],
                    "物料当前物理库存，按数量倒序取前 50", "物料库存", "件")


def low_stock(p: Params) -> Rendered:
    wh, b = _wh_clause("l.warehouse_id", p)
    b = {**p.binds(), **b}
    sql = f"""
        SELECT m.code, m.name,
               SUM(i.qty - i.locked_qty - i.frozen_qty) AS available,
               m.safety_stock
        FROM inventory i
        JOIN location l ON l.id = i.location_id
        JOIN material m ON m.id = i.sku_id
        WHERE i.sku_type = 'MATERIAL'{wh}
        GROUP BY m.code, m.name, m.safety_stock
        HAVING SUM(i.qty - i.locked_qty - i.frozen_qty) < m.safety_stock
        ORDER BY available
        LIMIT 5000
    """
    return Rendered(sql.strip(), b, ["编码", "名称", "可用", "安全库存"],
                    "可用库存低于安全库存的物料", "低库存物料", "件")


@dataclass
class Metric:
    key: str
    label: str
    builder: callable
    keywords: tuple[str, ...]
    needs_time: bool = True
    aliases: list[str] = field(default_factory=list)


# 顺序有意义：先匹配更具体的（低库存），再匹配泛化的（库存）
METRICS: list[Metric] = [
    Metric("low_stock", "低库存物料", low_stock, ("低库存", "缺货", "安全库存", "不足")),
    Metric("inventory_qty", "库存", inventory_qty, ("库存", "存量", "有多少"), needs_time=False),
    Metric("outbound_qty", "出库数量", outbound_qty,
           ("出库", "发货", "发出", "出了", "出货", "销售")),
    Metric("inbound_qty", "入库数量", inbound_qty,
           ("入库", "收货", "到货", "进库", "入了")),
]

BY_KEY = {m.key: m for m in METRICS}


def pick_metric(question: str) -> Metric | None:
    for m in METRICS:
        if any(k in question for k in m.keywords):
            return m
    return None


def default_window() -> tuple[datetime, datetime]:
    end = datetime.now()
    return end - timedelta(days=7), end
