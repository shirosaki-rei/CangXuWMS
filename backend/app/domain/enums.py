"""业务枚举。库列用 VARCHAR + CHECK（native_enum=False），加值不用改列。"""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    KEEPER = "KEEPER"          # 仓管员
    INSPECTOR = "INSPECTOR"    # 检验员
    SUPERVISOR = "SUPERVISOR"  # 仓库主管
    ADMIN = "ADMIN"            # 系统管理员
    INTEGRATION = "INTEGRATION"  # 集成账号（无 UI 权限）


class UserStatus(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class WarehouseType(StrEnum):
    MATERIAL = "MATERIAL"  # 原料
    PRODUCT = "PRODUCT"    # 成品
    AUX = "AUX"            # 辅料
    SLOW = "SLOW"          # 呆滞


class Switch(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class LocationType(StrEnum):
    NORMAL = "NORMAL"            # 普通
    STEREO = "STEREO"            # 立体
    CONSTANT_TEMP = "CONSTANT_TEMP"  # 恒温
    DANGEROUS = "DANGEROUS"      # 危品


class LocationStatus(StrEnum):
    IDLE = "IDLE"        # 空闲
    OCCUPIED = "OCCUPIED"  # 占用
    LOCKED = "LOCKED"    # 锁定
    MAINTAIN = "MAINTAIN"  # 维保


class SkuType(StrEnum):
    PRODUCT = "PRODUCT"
    MATERIAL = "MATERIAL"


class BarcodeType(StrEnum):
    ZONE = "ZONE"        # 库区
    LOCATION = "LOCATION"  # 库位
    MATERIAL = "MATERIAL"  # 物料
    BOX = "BOX"          # 箱码


class TempControl(StrEnum):
    NONE = "NONE"
    CONSTANT = "CONSTANT"
    COLD = "COLD"


class InboundType(StrEnum):
    PRODUCT = "PRODUCT"   # 产品入库 PI
    PURCHASE = "PURCHASE"  # 采购入库 PR
    RETURN = "RETURN"    # 生产退料 RT
    GAIN = "GAIN"        # 盘盈入库 SG


class OutboundType(StrEnum):
    SALES = "SALES"  # 销售出库 SO
    PICK = "PICK"    # 领料出库 PL
    LOSS = "LOSS"    # 盘亏出库 SL


class OrderStatus(StrEnum):
    """入库/出库单共用状态集（架构 6.2）。"""

    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    DONE = "DONE"
    VOID = "VOID"


class InspectionStatus(StrEnum):
    PENDING = "PENDING"
    CHECKING = "CHECKING"
    DONE = "DONE"


class InspectionResult(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    OVER_PASS = "OVER_PASS"
    FAIL = "FAIL"


class StocktakeType(StrEnum):
    FULL = "FULL"
    SPOT = "SPOT"
    CYCLE = "CYCLE"


class StocktakeMode(StrEnum):
    BLIND = "BLIND"
    OPEN = "OPEN"


class StocktakeStatus(StrEnum):
    PENDING = "PENDING"
    COUNTING = "COUNTING"
    CONFIRMING = "CONFIRMING"
    DONE = "DONE"
    CANCELED = "CANCELED"


class MoveStatus(StrEnum):
    PENDING = "PENDING"
    DOING = "DOING"
    DONE = "DONE"


class OutboundItemStatus(StrEnum):
    PENDING = "PENDING"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"


class BizType:
    """流水业务类型（txn.biz_type）。"""

    PURCHASE_IN = "PURCHASE_IN"
    PRODUCT_IN = "PRODUCT_IN"
    RETURN_IN = "RETURN_IN"
    GAIN_IN = "GAIN_IN"
    SALES_OUT = "SALES_OUT"
    PICK_OUT = "PICK_OUT"
    LOSS_OUT = "LOSS_OUT"
    MOVE = "MOVE"
    STOCKTAKE_IN = "STOCKTAKE_IN"
    STOCKTAKE_OUT = "STOCKTAKE_OUT"
    VOID_REVERSE = "VOID_REVERSE"


class CheckLevel(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"
    LOG = "LOG"
    SKIP = "SKIP"
    TIMEOUT = "TIMEOUT"


class AiSuggestionType(StrEnum):
    LOCATION = "LOCATION"
    PATH = "PATH"
    CHECK = "CHECK"


class FeedbackAction(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    REVOKE = "REVOKE"


class MetricScene(StrEnum):
    LOCATE = "LOCATE"
    PICK = "PICK"
    CHECK = "CHECK"
    QUERY = "QUERY"


class ConfigScope(StrEnum):
    GLOBAL = "GLOBAL"
    SUPPLIER = "SUPPLIER"


class ValueType(StrEnum):
    INT = "INT"
    DECIMAL = "DECIMAL"
    BOOL = "BOOL"
    ENUM = "ENUM"
    STRING = "STRING"


class ReconcileDirection(StrEnum):
    MES = "MES"
    ERP = "ERP"


class DiffType(StrEnum):
    STATUS = "STATUS"
    QTY = "QTY"
    MISSING = "MISSING"
    EXTRA = "EXTRA"
