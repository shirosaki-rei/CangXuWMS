"""测试辅助：重置数据库（drop_all + create_all + seed）。

跑 e2e-b02 / e2e-b03 前必须用它——那两个脚本扫的是种子单据，
跑过一次后单据已判定/已出库，seed 又是按单号幂等的，不会重置状态。

用法：python tools/reset_db.py
"""
from __future__ import annotations

from app.core.db import SessionLocal, create_all, drop_all
from app.seed import seed


def main() -> None:
    drop_all()
    create_all()
    with SessionLocal() as s:
        stats = seed(s)
    print("reset done:", stats)


if __name__ == "__main__":
    main()
