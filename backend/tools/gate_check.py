"""上线 Gate 检查（T-05-7 / PRD 12.6）。

G1 库位坐标覆盖率 100%（缺坐标的库位不参与 AI 推荐）
G2 物料/产品属性完整率 ≥ 95%（weight/volume 等，AI 打分与容量校验要用）
G3 近 30 天有库存流水（没有流水的系统等于没跑过）

用法：python tools/gate_check.py  （可用环境变量覆盖阈值）
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.domain.models import Inventory, Location, Material, Product, Txn

G2_MIN = float(os.getenv("GATE_G2_MIN", "0.95"))
G3_DAYS = int(os.getenv("GATE_G3_DAYS", "30"))


def check() -> tuple[bool, list[str]]:
    lines: list[str] = []
    ok = True
    with SessionLocal() as s:
        # G1
        total = s.execute(select(func.count()).select_from(Location)).scalar() or 0
        missing = s.execute(
            select(func.count()).select_from(Location).where(
                (Location.coord_x.is_(None)) | (Location.coord_y.is_(None)))
        ).scalar() or 0
        g1 = (total - missing) / total if total else 0
        ok &= g1 >= 1.0
        lines.append(f"G1 库位坐标：{total - missing}/{total} = {g1 * 100:.1f}%"
                     f"（要求 100%）{'  ✗' if g1 < 1 else '  ✓'}")

        # G2：属性完整率 = 有 weight 且 有 volume 的 SKU 占比
        for model, label in ((Material, "物料"), (Product, "产品")):
            n = s.execute(select(func.count()).select_from(model)).scalar() or 0
            good = s.execute(
                select(func.count()).select_from(model).where(
                    model.weight_kg.is_not(None), model.volume_m3.is_not(None))
            ).scalar() or 0
            rate = good / n if n else 1.0
            ok &= rate >= G2_MIN
            lines.append(f"G2 {label}属性完整率：{good}/{n} = {rate * 100:.1f}%"
                         f"（要求 ≥ {G2_MIN * 100:.0f}%）{'  ✗' if rate < G2_MIN else '  ✓'}")

        # G3
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=G3_DAYS)
        n_txn = s.execute(select(func.count()).select_from(Txn).where(
            Txn.created_at >= since)).scalar() or 0
        ok &= n_txn > 0
        lines.append(f"G3 近 {G3_DAYS} 天库存流水：{n_txn} 条"
                     f"{'  ✓' if n_txn else '  ✗（系统还没跑过业务）'}")

        n_inv = s.execute(select(func.count()).select_from(Inventory)).scalar() or 0
        lines.append(f"参考：库存行 {n_inv} 条")

    return ok, lines


def main() -> int:
    ok, lines = check()
    print("上线 Gate 检查")
    for l in lines:
        print("  " + l)
    print("\n结论：" + ("通过" if ok else "未通过，按 PRD 12.6 降级或延后上线"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
