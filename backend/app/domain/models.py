"""SQLAlchemy 模型。DDL 单一数据源：docs/WMS架构设计文档.md 6.2，共 30 张表。

约定：
- 枚举列一律 VARCHAR + CHECK（native_enum=False），加枚举值不必改列；
- 时间列存 naive UTC，读写都走 domain.timeutil.utcnow()；
- 除 inventory / txn 外，其它表不允许在 service 外直接 UPDATE（见 domain/stock.py）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    quoted_name,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# SQLite 下 BIGINT 主键不会自动成为 rowid 别名，导致自增失效；
# 用 with_variant 让 SQLite 走 INTEGER，MySQL 仍为 BIGINT。
BigInt = BigInteger().with_variant(Integer, "sqlite")

# 约束命名固定，Alembic 自动生成的迁移才能稳定 diff
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)


class CreatedMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class UpdatedMixin:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=utcnow, nullable=False
    )


_TABLE_ARGS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


# ---------------------------------------------------------------- 主数据
class Warehouse(IdMixin, CreatedMixin, Base):
    __tablename__ = "warehouse"
    __table_args__ = {**_TABLE_ARGS, "comment": "仓库"}

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(16))  # MATERIAL/PRODUCT/AUX/SLOW
    status: Mapped[str] = mapped_column(String(16), default="ENABLED")
    owner_id: Mapped[int | None] = mapped_column(BigInt)


class Supplier(IdMixin, CreatedMixin, Base):
    __tablename__ = "supplier"
    __table_args__ = {**_TABLE_ARGS, "comment": "供应商档案"}

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    # NULL = 用全局默认（BR-023）
    over_receive: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    contact: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="ENABLED")


class Material(IdMixin, CreatedMixin, Base):
    __tablename__ = "material"
    __table_args__ = {**_TABLE_ARGS, "comment": "物料"}

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str] = mapped_column(String(16))
    safety_stock: Mapped[int] = mapped_column(Integer, default=0)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))  # Gate G2 统计字段
    volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    is_dangerous: Mapped[bool] = mapped_column(Boolean, default=False)
    temp_control: Mapped[str] = mapped_column(String(16), default="NONE")


class Product(IdMixin, CreatedMixin, Base):
    __tablename__ = "product"
    __table_args__ = {**_TABLE_ARGS, "comment": "产品"}

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    spec: Mapped[str | None] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(16), default="台")
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    is_dangerous: Mapped[bool] = mapped_column(Boolean, default=False)
    temp_control: Mapped[str] = mapped_column(String(16), default="NONE")


class Barcode(IdMixin, CreatedMixin, Base):
    __tablename__ = "barcode"
    __table_args__ = {**_TABLE_ARGS, "comment": "条码（全局唯一 BR-009）"}

    code: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[str] = mapped_column(String(16))  # ZONE/LOCATION/MATERIAL/BOX
    ref_id: Mapped[int | None] = mapped_column(BigInt)


# ---------------------------------------------------------------- 账号与权限
class User(IdMixin, CreatedMixin, Base):
    __tablename__ = quoted_name("user", True)  # MySQL 关键字，全程反引号
    __table_args__ = {**_TABLE_ARGS, "comment": "账号"}

    username: Mapped[str] = mapped_column(String(32), unique=True)
    password: Mapped[str] = mapped_column(String(100))  # bcrypt cost=12
    name: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(20))  # 日志中掩码
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="ENABLED")
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)


class UserWarehouse(Base):
    """数据权限：用户可见仓库范围，接口 1.4 要求在依赖注入层强制注入。"""

    __tablename__ = "user_warehouse"
    __table_args__ = (UniqueConstraint("user_id", "warehouse_id"), _TABLE_ARGS)

    user_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("warehouse.id", ondelete="CASCADE"), primary_key=True
    )


class ApiClient(IdMixin, CreatedMixin, Base):
    __tablename__ = "api_client"
    __table_args__ = {**_TABLE_ARGS, "comment": "集成账号（MES/ERP）"}

    app_key: Mapped[str] = mapped_column(String(32), unique=True)
    app_secret: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))  # MES/ERP
    status: Mapped[str] = mapped_column(String(16), default="ENABLED")


# ---------------------------------------------------------------- 库位与库存
class Location(IdMixin, CreatedMixin, Base):
    __tablename__ = "location"
    __table_args__ = {**_TABLE_ARGS, "comment": "库位（坐标必填由 Gate G1 保证）"}

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(16), default="NORMAL")
    warehouse_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("warehouse.id"), index=True
    )
    cap_pallet: Mapped[int] = mapped_column(Integer, default=0)
    cap_material: Mapped[int] = mapped_column(Integer, default=0)
    used_pallet: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="IDLE")
    coord_x: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    coord_y: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    dist_to_dock: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    dist_to_pack: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=utcnow, nullable=False
    )


class Inventory(IdMixin, Base):
    """唯一会并发写的表。可用量 = qty - locked_qty - frozen_qty，不落库。"""

    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("sku_type", "sku_id", "location_id"),
        CheckConstraint("qty >= 0", name="qty_nonneg"),
        CheckConstraint("locked_qty >= 0", name="locked_nonneg"),
        CheckConstraint("frozen_qty >= 0", name="frozen_nonneg"),
        _TABLE_ARGS,
    )

    sku_type: Mapped[str] = mapped_column(String(16))
    sku_id: Mapped[int] = mapped_column(BigInt, index=True)
    location_id: Mapped[int] = mapped_column(BigInt, index=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    locked_qty: Mapped[int] = mapped_column(Integer, default=0)
    frozen_qty: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=utcnow, nullable=False
    )

    @property
    def available(self) -> int:
        return self.qty - self.locked_qty - self.frozen_qty


class Txn(CreatedMixin, Base):
    """库存流水，只增不删（BR-002）。"""

    __tablename__ = "txn"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    sku_type: Mapped[str] = mapped_column(String(16))
    sku_id: Mapped[int] = mapped_column(BigInt)
    location_id: Mapped[int] = mapped_column(BigInt)
    qty_delta: Mapped[int] = mapped_column(Integer)  # 正入负出
    balance: Mapped[int] = mapped_column(Integer)  # 事务后结存
    biz_type: Mapped[str] = mapped_column(String(24))
    biz_no: Mapped[str] = mapped_column(String(32))
    operator_id: Mapped[int] = mapped_column(BigInt)


class InTransit(IdMixin, UpdatedMixin, Base):
    __tablename__ = "in_transit"
    __table_args__ = (UniqueConstraint("po_no", "sku_type", "sku_id"), _TABLE_ARGS)

    sku_type: Mapped[str] = mapped_column(String(16))
    sku_id: Mapped[int] = mapped_column(BigInt)
    po_no: Mapped[str] = mapped_column(String(32))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    eta: Mapped[datetime | None] = mapped_column(Date)


# ---------------------------------------------------------------- 入库单
class InboundOrder(IdMixin, CreatedMixin, Base):
    __tablename__ = "inbound_order"
    __table_args__ = {**_TABLE_ARGS, "comment": "入库单"}

    no: Mapped[str] = mapped_column(String(32), unique=True)
    type: Mapped[str] = mapped_column(String(16))  # PRODUCT/PURCHASE/RETURN/GAIN
    source_no: Mapped[str | None] = mapped_column(String(32))
    supplier_id: Mapped[int | None] = mapped_column(BigInt)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    plan_qty: Mapped[int] = mapped_column(Integer, default=0)
    actual_qty: Mapped[int] = mapped_column(Integer, default=0)
    config_snapshot: Mapped[dict | None] = mapped_column(JSON)  # BR-026
    version: Mapped[int] = mapped_column(Integer, default=0)
    creator_id: Mapped[int] = mapped_column(BigInt)
    checker_id: Mapped[int | None] = mapped_column(BigInt)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class InboundItem(IdMixin, Base):
    __tablename__ = "inbound_item"
    __table_args__ = {**_TABLE_ARGS, "comment": "入库明细"}

    order_id: Mapped[int] = mapped_column(BigInt, ForeignKey("inbound_order.id"))
    sku_id: Mapped[int] = mapped_column(BigInt)
    box_code: Mapped[str | None] = mapped_column(String(64))
    sn: Mapped[str | None] = mapped_column(String(64))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    location_id: Mapped[int | None] = mapped_column(BigInt)


# ---------------------------------------------------------------- 出库单
class OutboundOrder(IdMixin, CreatedMixin, Base):
    __tablename__ = "outbound_order"
    __table_args__ = {**_TABLE_ARGS, "comment": "出库单"}

    no: Mapped[str] = mapped_column(String(32), unique=True)
    type: Mapped[str] = mapped_column(String(16))  # SALES/PICK/LOSS
    source_no: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    plan_qty: Mapped[int] = mapped_column(Integer, default=0)
    actual_qty: Mapped[int] = mapped_column(Integer, default=0)
    config_snapshot: Mapped[dict | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=0)
    creator_id: Mapped[int] = mapped_column(BigInt)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class OutboundItem(IdMixin, Base):
    __tablename__ = "outbound_item"
    __table_args__ = {**_TABLE_ARGS, "comment": "出库明细（逐件 SN）"}

    order_id: Mapped[int] = mapped_column(BigInt, ForeignKey("outbound_order.id"))
    sku_id: Mapped[int] = mapped_column(BigInt)
    sn: Mapped[str | None] = mapped_column(String(64))
    location_id: Mapped[int | None] = mapped_column(BigInt)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    operator_id: Mapped[int | None] = mapped_column(BigInt)
    operated_at: Mapped[datetime | None] = mapped_column(DateTime)


# ---------------------------------------------------------------- 检验 / 盘点 / 移位
class Inspection(IdMixin, CreatedMixin, Base):
    __tablename__ = "inspection"
    __table_args__ = {**_TABLE_ARGS, "comment": "来料检验单"}

    no: Mapped[str] = mapped_column(String(32), unique=True)
    supplier_id: Mapped[int] = mapped_column(BigInt, ForeignKey("supplier.id"))
    logistics_no: Mapped[str | None] = mapped_column(String(64))
    plate_no: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    result: Mapped[str | None] = mapped_column(String(16))  # PASS/PARTIAL/OVER_PASS/FAIL
    plan_qty: Mapped[int] = mapped_column(Integer, default=0)
    actual_qty: Mapped[int] = mapped_column(Integer, default=0)
    fail_reason: Mapped[str | None] = mapped_column(String(255))
    creator_id: Mapped[int] = mapped_column(BigInt)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, default=0)


class InspectionItem(IdMixin, Base):
    __tablename__ = "inspection_item"
    __table_args__ = {**_TABLE_ARGS, "comment": "检验明细"}

    inspection_id: Mapped[int] = mapped_column(BigInt, ForeignKey("inspection.id"))
    material_id: Mapped[int] = mapped_column(BigInt)
    plan_qty: Mapped[int] = mapped_column(Integer, default=0)
    actual_qty: Mapped[int] = mapped_column(Integer, default=0)
    barcode: Mapped[str | None] = mapped_column(String(64))
    qualified: Mapped[bool | None] = mapped_column(Boolean)  # NULL=未判定


class Stocktake(IdMixin, CreatedMixin, Base):
    __tablename__ = "stocktake"
    __table_args__ = {**_TABLE_ARGS, "comment": "盘点单"}

    no: Mapped[str] = mapped_column(String(32), unique=True)
    type: Mapped[str] = mapped_column(String(16))  # FULL/SPOT/CYCLE
    warehouse_id: Mapped[int] = mapped_column(BigInt, ForeignKey("warehouse.id"))
    mode: Mapped[str] = mapped_column(String(16), default="BLIND")  # 创建时固化（BR-024）
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    diff_loss: Mapped[int] = mapped_column(Integer, default=0)
    diff_gain: Mapped[int] = mapped_column(Integer, default=0)
    operator_id: Mapped[int] = mapped_column(BigInt)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, default=0)


class StocktakeItem(IdMixin, Base):
    __tablename__ = "stocktake_item"
    __table_args__ = (
        UniqueConstraint("stocktake_id", "location_id", "material_id"),
        _TABLE_ARGS,
    )

    stocktake_id: Mapped[int] = mapped_column(BigInt, ForeignKey("stocktake.id"))
    material_id: Mapped[int] = mapped_column(BigInt)
    location_id: Mapped[int] = mapped_column(BigInt)
    book_qty: Mapped[int] = mapped_column(Integer, default=0)  # 盲盘对操作员不可见
    real_qty: Mapped[int | None] = mapped_column(Integer)  # NULL=未盘


class MoveOrder(IdMixin, CreatedMixin, Base):
    __tablename__ = "move_order"
    __table_args__ = {**_TABLE_ARGS, "comment": "移位单"}

    no: Mapped[str] = mapped_column(String(32), unique=True)
    material_id: Mapped[int] = mapped_column(BigInt)
    from_loc_id: Mapped[int] = mapped_column(BigInt)
    to_loc_id: Mapped[int] = mapped_column(BigInt)
    qty: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    operator_id: Mapped[int] = mapped_column(BigInt)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


# ---------------------------------------------------------------- AI
class AiSuggestion(IdMixin, CreatedMixin, Base):
    __tablename__ = "ai_suggestion"
    __table_args__ = {**_TABLE_ARGS, "comment": "AI 建议记录"}

    trace_id: Mapped[str] = mapped_column(String(32), unique=True)
    type: Mapped[str] = mapped_column(String(16))  # LOCATION/PATH/CHECK
    target_id: Mapped[int] = mapped_column(BigInt)
    payload: Mapped[dict] = mapped_column(JSON)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    reasons: Mapped[list | None] = mapped_column(JSON)


class AiFeedback(IdMixin, CreatedMixin, Base):
    __tablename__ = "ai_feedback"
    __table_args__ = {**_TABLE_ARGS, "comment": "建议反馈（X05 采纳率唯一来源）"}

    suggestion_id: Mapped[int] = mapped_column(BigInt, ForeignKey("ai_suggestion.id"))
    action: Mapped[str] = mapped_column(String(16))  # ACCEPT/REJECT/REVOKE
    reason: Mapped[str | None] = mapped_column(String(64))
    operator_id: Mapped[int] = mapped_column(BigInt)


class MetricEvent(IdMixin, CreatedMixin, Base):
    __tablename__ = "metric_event"
    __table_args__ = {**_TABLE_ARGS, "comment": "AI 结果指标埋点"}

    scene: Mapped[str] = mapped_column(String(16))  # LOCATE/PICK/CHECK/QUERY
    trace_id: Mapped[str] = mapped_column(String(32))
    order_type: Mapped[str | None] = mapped_column(String(16))
    order_id: Mapped[int | None] = mapped_column(BigInt)
    user_id: Mapped[int] = mapped_column(BigInt)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    distance_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    baseline_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    ai_used: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------- 校验与运维
class CheckResult(IdMixin, CreatedMixin, Base):
    __tablename__ = "check_result"
    __table_args__ = {**_TABLE_ARGS, "comment": "提交前校验结果（留存 ≥180 天 BR-018）"}

    trace_id: Mapped[str] = mapped_column(String(32))
    order_type: Mapped[str] = mapped_column(String(16))  # INBOUND/OUTBOUND/STOCKTAKE
    order_id: Mapped[int] = mapped_column(BigInt)
    rules: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))  # PASS/SUBMITTED_WITH_WARN/BLOCKED
    reason: Mapped[str | None] = mapped_column(String(255))  # 带预警提交必填（BR-016）
    version: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)


class LlmUsage(IdMixin, CreatedMixin, Base):
    __tablename__ = "llm_usage"
    __table_args__ = {**_TABLE_ARGS, "comment": "LLM 调用用量"}

    trace_id: Mapped[str] = mapped_column(String(32))
    scene: Mapped[str] = mapped_column(String(16))  # QUERY/CHECK_REASON
    model: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)


class NlQueryLog(IdMixin, CreatedMixin, Base):
    __tablename__ = "nl_query_log"
    __table_args__ = {**_TABLE_ARGS, "comment": "问数日志"}

    trace_id: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[int] = mapped_column(BigInt)
    question: Mapped[str] = mapped_column(String(255))
    intent: Mapped[str | None] = mapped_column(String(32))
    metric: Mapped[str | None] = mapped_column(String(64))  # NULL=未命中
    generated_sql: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[bool] = mapped_column(Boolean, default=False)


class ReconcileDiff(IdMixin, CreatedMixin, Base):
    __tablename__ = "reconcile_diff"
    __table_args__ = (
        UniqueConstraint("biz_date", "direction", "biz_no", "diff_type"),
        _TABLE_ARGS,
    )

    biz_date: Mapped[datetime] = mapped_column(Date)
    direction: Mapped[str] = mapped_column(String(16))  # MES/ERP
    biz_no: Mapped[str] = mapped_column(String(32))
    diff_type: Mapped[str] = mapped_column(String(16))  # STATUS/QTY/MISSING/EXTRA
    local_val: Mapped[str | None] = mapped_column(String(128))
    remote_val: Mapped[str | None] = mapped_column(String(128))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class OpLog(IdMixin, CreatedMixin, Base):
    """幂等与审计。client_op_id 唯一索引是 Redis 键过期后的兜底（接口 1.3）。"""

    __tablename__ = "op_log"
    __table_args__ = {**_TABLE_ARGS, "comment": "幂等与审计"}

    client_op_id: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[int | None] = mapped_column(BigInt)
    path: Mapped[str] = mapped_column(String(120))
    result: Mapped[dict | None] = mapped_column(JSON)


class SysConfig(IdMixin, Base):
    __tablename__ = "sys_config"
    __table_args__ = (
        UniqueConstraint("cfg_key", "scope", "scope_id"),
        _TABLE_ARGS,
    )

    cfg_key: Mapped[str] = mapped_column(String(64))
    cfg_value: Mapped[str] = mapped_column(String(255))
    value_type: Mapped[str] = mapped_column(String(16))  # INT/DECIMAL/BOOL/ENUM/STRING
    scope: Mapped[str] = mapped_column(String(16), default="GLOBAL")  # GLOBAL/SUPPLIER
    scope_id: Mapped[int | None] = mapped_column(BigInt)
    remark: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[int | None] = mapped_column(BigInt)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=utcnow, nullable=False
    )
