"""种子数据（T-00-3）：仓库 / 库位 / 物料 / 产品 / 账号 / 规则配置。

幂等：已存在同编码记录则跳过，可重复执行。
用法：`python -m app.seed`

注意：跑 pytest 会在每个用例前后清空全表，跑完测试后需要重新执行本模块。
"""
from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, create_all, engine
from app.core.security import hash_password, verify_password
from app.domain.models import (
    ApiClient,
    Barcode,
    InboundItem,
    InboundOrder,
    Inspection,
    InspectionItem,
    Location,
    Material,
    OutboundItem,
    OutboundOrder,
    Product,
    Supplier,
    SysConfig,
    User,
    UserWarehouse,
    Warehouse,
)
from app.domain.enums import (
    BarcodeType,
    LocationType,
    Role,
    TempControl,
    WarehouseType,
)

# PRD 6.9 的 10 个配置项
CONFIGS = [
    ("over_receive_ratio", "0.05", "DECIMAL", "超收阈值（BR-005/BR-023，供应商可覆盖）"),
    ("qty_deviation_ratio", "0.10", "DECIMAL", "数量偏差阈值（校验 R1）"),
    ("stocktake_mode", "BLIND", "ENUM", "盘点方式默认盲盘（BR-024，创建时固化）"),
    ("diff_rate_ratio", "0.05", "DECIMAL", "盘点差异率阈值（校验 R9）"),
    ("coord_required", "true", "BOOL", "库位坐标必填（BR-025 / Gate G1）"),
    ("attr_complete_ratio", "0.95", "DECIMAL", "属性完整率下限（Gate G2）"),
    ("ai_enabled", "true", "BOOL", "建议展示总开关（BR-020）"),
    ("silent_days", "7", "INT", "单类建议静默期（BR-021）"),
    ("query_enabled", "true", "BOOL", "问数功能开关（BR-020）"),
    ("adoption_offline_ratio", "0.30", "DECIMAL", "采纳率下线阈值（BR-022）"),
]

WAREHOUSES = [
    ("WH-001", "1#原料仓", WarehouseType.MATERIAL),
    ("WH-002", "2#成品仓", WarehouseType.PRODUCT),
    ("WH-003", "3#辅料仓", WarehouseType.AUX),
]

MATERIALS = [
    ("BAT-LIPO-4500-003", "锂聚合物电池 4500mAh", "原料", "PCS", 200, Decimal("0.045"), False, TempControl.NONE),
    ("DSP-AMOLED-67-FULL", "AMOLED 显示屏 6.7", "原料", "PCS", 100, Decimal("0.120"), False, TempControl.NONE),
    ("PCB-MAIN-V3", "主板 PCB V3", "原料", "PCS", 150, Decimal("0.080"), False, TempControl.NONE),
    ("CAM-WIDE-48M", "广角摄像头 4800 万", "原料", "PCS", 80, Decimal("0.021"), False, TempControl.NONE),
    ("SOL-IPA-99", "清洗酒精 99%", "辅件", "L", 50, Decimal("0.850"), True, TempControl.NONE),
    ("GLUE-UV-50G", "UV 固化胶 50g", "辅件", "支", 300, Decimal("0.050"), False, TempControl.CONSTANT),
]

PRODUCTS = [
    ("A3288", "iphone16", "尺寸 6.1 / 屏幕 OLED / 分辨率 2556×1179 / 亮度 2000nit", "台", Decimal("0.171"), False, TempControl.NONE),
    ("A3399", "iphone16 Pro", "尺寸 6.3 / 屏幕 OLED / 分辨率 2622×1206 / 亮度 2000nit", "台", Decimal("0.199"), False, TempControl.NONE),
    ("B2100", "Galaxy S26", "尺寸 6.2 / 屏幕 AMOLED / 分辨率 2340×1080 / 亮度 2600nit", "台", Decimal("0.162"), False, TempControl.NONE),
    ("C5500", "Mate 70", "尺寸 6.7 / 屏幕 OLED / 分辨率 2688×1216 / 亮度 1800nit", "台", Decimal("0.209"), False, TempControl.NONE),
]

SUPPLIERS = [
    ("GYS-ZTE-001", "中兴通讯股份有限公司", None, "021-68830000"),
    ("GYS-BYD-002", "比亚迪股份有限公司", Decimal("0.08"), "0755-89888888"),
    ("GYS-LUX-003", "立讯精密工业股份有限公司", None, "0512-62580000"),
]


def _locations_for(warehouse_id: int, prefix: str, count: int, dangerous: bool = False):
    """A1-01-01 形式的库位，带坐标（Gate G1 要求 100%）。"""
    out = []
    for i in range(1, count + 1):
        zone = chr(ord("A") + (i - 1) // 12)
        code = f"{zone}{prefix}-{(i - 1) % 12 + 1:02d}-{warehouse_id:02d}"
        out.append(
            Location(
                code=code,
                name=f"{zone}{prefix} 库位 {i}",
                type=LocationType.DANGEROUS if dangerous else LocationType.NORMAL,
                warehouse_id=warehouse_id,
                cap_pallet=8,
                cap_material=200,
                coord_x=Decimal((i - 1) % 12 * 2 + 1),
                coord_y=Decimal((i - 1) // 12 * 3 + 1),
                dist_to_dock=Decimal(20 + i),
                dist_to_pack=Decimal(12 + i % 9),
            )
        )
    return out


def seed(session: Session) -> dict:
    stats = {"warehouse": 0, "location": 0, "material": 0, "product": 0,
             "supplier": 0, "user": 0, "barcode": 0, "sys_config": 0, "api_client": 0,
             "inspection": 0, "inbound_order": 0, "outbound_order": 0}

    def has(model, **kw) -> bool:
        return session.execute(select(model).filter_by(**kw)).first() is not None

    # 仓库 + 库位
    wh_ids = {}
    for code, name, wtype in WAREHOUSES:
        if has(Warehouse, code=code):
            wh_ids[code] = session.execute(
                select(Warehouse.id).where(Warehouse.code == code)
            ).scalar_one()
            continue
        w = Warehouse(code=code, name=name, type=str(wtype))
        session.add(w)
        session.flush()
        wh_ids[code] = w.id
        stats["warehouse"] += 1

    for code, name, wtype in WAREHOUSES:
        wid = wh_ids[code]
        if not session.execute(select(Location.id).where(Location.warehouse_id == wid)).first():
            for loc in _locations_for(wid, "1", 12):
                session.add(loc)
                stats["location"] += 1

    # 危品库位（BR-013 演示用）
    wid = wh_ids["WH-003"]
    if not session.execute(
        select(Location.id).where(Location.warehouse_id == wid, Location.type == "DANGEROUS")
    ).first():
        for loc in _locations_for(wid, "2", 4, dangerous=True):
            session.add(loc)
            stats["location"] += 1

    # 物料 / 产品
    for code, name, mtype, unit, safety, weight, danger, temp in MATERIALS:
        if has(Material, code=code):
            continue
        session.add(Material(code=code, name=name, type=mtype, unit=unit, safety_stock=safety,
                             weight_kg=weight,
                             # 体积按重量估（Gate G2 要求属性完整率 100%）
                             volume_m3=(float(weight) * 2 if weight is not None else None),
                             is_dangerous=danger, temp_control=str(temp)))
        stats["material"] += 1

    for code, name, spec, unit, weight, danger, temp in PRODUCTS:
        if has(Product, code=code):
            continue
        session.add(Product(code=code, name=name, spec=spec, unit=unit, weight_kg=weight,
                            volume_m3=(float(weight) * 1.5 if weight is not None else None),
                            is_dangerous=danger, temp_control=str(temp)))
        stats["product"] += 1

    # 供应商
    for code, name, over, contact in SUPPLIERS:
        if has(Supplier, code=code):
            continue
        session.add(Supplier(code=code, name=name, over_receive=over, contact=contact))
        stats["supplier"] += 1

    # 账号：五种角色各一个。演示账号密码同用户名；admin 的密码取 SEED_ADMIN_PASSWORD。
    # 本项目没有改密接口，密码只能由种子决定，所以每次 seed 都按 .env 校正 admin 密码
    # （.env 是唯一真相源），顺带清掉密码不一致期间累积的失败计数与锁定。
    accounts = [
        ("admin", "张伟", Role.ADMIN, None, "13800000001"),
        ("supervisor", "陈芳", Role.SUPERVISOR, None, "13800000002"),
        ("wangjf", "王建峰", Role.KEEPER, ["WH-001", "WH-002"], "13812345678"),
        ("liq", "李强", Role.INSPECTOR, ["WH-001"], "13900000003"),
        ("mes-prod", "MES 接口账号", Role.INTEGRATION, None, None),
    ]
    for username, name, role, whs, phone in accounts:
        is_admin = username == settings.seed_admin_username
        pwd = settings.seed_admin_password if is_admin else username
        u = session.execute(select(User).filter_by(username=username)).scalars().first()
        if u is None:
            u = User(username=username, name=name, role=str(role), phone=phone,
                     password=hash_password(pwd))
            session.add(u)
            session.flush()
            stats["user"] += 1
            if whs:
                for c in whs:
                    session.add(UserWarehouse(user_id=u.id, warehouse_id=wh_ids[c]))
            continue
        if is_admin:
            changed = not verify_password(pwd, u.password)
            if changed:
                u.password = hash_password(pwd)
            if changed or u.fail_count or u.locked_until:
                u.fail_count = 0
                u.locked_until = None
                stats["admin_password_reset"] = stats.get("admin_password_reset", 0) + 1

    # 条码：每类各一条
    for code, btype, ref in [("KQ-001", BarcodeType.ZONE, None),
                             ("KQ-002", BarcodeType.LOCATION, None),
                             ("KQ-003", BarcodeType.MATERIAL, None),
                             ("KQ-004", BarcodeType.BOX, None)]:
        if has(Barcode, code=code):
            continue
        session.add(Barcode(code=code, type=str(btype), ref_id=ref))
        stats["barcode"] += 1

    # 规则配置
    for key, value, vtype, remark in CONFIGS:
        if has(SysConfig, cfg_key=key, scope="GLOBAL", scope_id=None):
            continue
        session.add(SysConfig(cfg_key=key, cfg_value=value, value_type=vtype,
                              scope="GLOBAL", remark=remark))
        stats["sys_config"] += 1

    # 集成账号
    if not has(ApiClient, app_key="mes-prod"):
        session.add(ApiClient(app_key="mes-prod", app_secret="mes-secret-change-me",
                              name="MES 生产系统", source="MES"))
        stats["api_client"] += 1

    # 来料检验单：一条待检、一条已检合格（后者可直接生成采购入库单）
    if not has(Inspection, no="JY20260127001"):
        sup_id = session.execute(
            select(Supplier.id).where(Supplier.code == "GYS-ZTE-001")
        ).scalar_one()
        mat_id = session.execute(
            select(Material.id).where(Material.code == "BAT-LIPO-4500-003")
        ).scalar_one()
        insp = Inspection(no="JY20260127001", supplier_id=sup_id,
                          logistics_no="WL20260127001", plate_no="京A12345",
                          status="PENDING", plan_qty=500, actual_qty=0, creator_id=1)
        session.add(insp)
        session.flush()
        session.add(InspectionItem(inspection_id=insp.id, material_id=mat_id,
                                   plan_qty=500, actual_qty=0))
        stats["inspection"] = stats.get("inspection", 0) + 1

    if not has(Inspection, no="JY20260127002"):
        sup_id = session.execute(
            select(Supplier.id).where(Supplier.code == "GYS-BYD-002")
        ).scalar_one()
        mat_id = session.execute(
            select(Material.id).where(Material.code == "DSP-AMOLED-67-FULL")
        ).scalar_one()
        insp = Inspection(no="JY20260127002", supplier_id=sup_id,
                          logistics_no="WL20260127002", plate_no="京B66666",
                          status="DONE", result="PASS", plan_qty=200, actual_qty=200,
                          creator_id=1, checked_at=datetime(2026, 1, 27, 14, 0, 0))
        session.add(insp)
        session.flush()
        session.add(InspectionItem(inspection_id=insp.id, material_id=mat_id,
                                   plan_qty=200, actual_qty=200, qualified=True))
        stats["inspection"] = stats.get("inspection", 0) + 1

    # 采购入库单：关联已检合格的检验单，待入库
    if not has(InboundOrder, no="PR20260127001"):
        sup_id = session.execute(
            select(Supplier.id).where(Supplier.code == "GYS-BYD-002")
        ).scalar_one()
        mat_id = session.execute(
            select(Material.id).where(Material.code == "DSP-AMOLED-67-FULL")
        ).scalar_one()
        order = InboundOrder(no="PR20260127001", type="PURCHASE",
                             source_no="JY20260127002", supplier_id=sup_id,
                             status="PENDING", plan_qty=200, actual_qty=0, creator_id=1)
        session.add(order)
        session.flush()
        session.add(InboundItem(order_id=order.id, sku_id=mat_id, qty=0))
        stats["inbound_order"] = stats.get("inbound_order", 0) + 1

    # 产品入库单：MES 推送类型，本机 seed 造一条，让成品出库流可测
    if not has(InboundOrder, no="PI20260127001"):
        prod = session.execute(
            select(Product.id).where(Product.code == "A3288")
        ).scalar_one()
        o = InboundOrder(no="PI20260127001", type="PRODUCT", source_no="RWD20260127001",
                         status="PENDING", plan_qty=40, actual_qty=0, creator_id=1)
        session.add(o)
        session.flush()
        session.add(InboundItem(order_id=o.id, sku_id=prod, qty=0))
        stats["inbound_order"] = stats.get("inbound_order", 0) + 1

    # 出库单：一张销售出库（成品 A3288）、一张领料出库（物料），都待出库
    if not has(OutboundOrder, no="SO20260127001"):
        prod = session.execute(
            select(Product.id).where(Product.code == "A3288")
        ).scalar_one()
        o = OutboundOrder(no="SO20260127001", type="SALES", source_no="XSDD20260127001",
                          status="PENDING", plan_qty=20, actual_qty=0, creator_id=1)
        session.add(o)
        session.flush()
        session.add(OutboundItem(order_id=o.id, sku_id=prod, status="PENDING"))
        stats["outbound_order"] = stats.get("outbound_order", 0) + 1

    if not has(OutboundOrder, no="PL20260127001"):
        mat = session.execute(
            select(Material.id).where(Material.code == "DSP-AMOLED-67-FULL")
        ).scalar_one()
        o = OutboundOrder(no="PL20260127001", type="PICK", source_no="SCLL20260127001",
                          status="PENDING", plan_qty=120, actual_qty=0, creator_id=1)
        session.add(o)
        session.flush()
        session.add(OutboundItem(order_id=o.id, sku_id=mat, status="PENDING"))
        stats["outbound_order"] = stats.get("outbound_order", 0) + 1

    session.commit()
    return stats


def main() -> int:
    create_all()
    with SessionLocal() as s:
        stats = seed(s)
    total = sum(stats.values())
    print(f"seed done: {stats} (新增 {total} 条；已存在的记录自动跳过)")
    if total == 0:
        print("数据库已是种子状态，无需重复执行。")
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
