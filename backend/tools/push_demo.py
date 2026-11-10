"""演示用：以 MES 身份推一张单据给集成接口（带 HMAC 签名）。

接口文档 4.1 的签名算法：hex(hmac_sha256(app_secret, app_key + timestamp + body_raw))。
演示时用它证明「外部系统对接」是真跑通的，而不是靠后台直接改库。

用法（在 backend 目录）：
    PYTHONPATH=. ./.venv/Scripts/python.exe tools/push_demo.py
    PYTHONPATH=. ./.venv/Scripts/python.exe tools/push_demo.py --kind outbound
    PYTHONPATH=. ./.venv/Scripts/python.exe tools/push_demo.py --url http://127.0.0.1:8000/api/v1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from app.core.integration_auth import sign

APP_KEY = "mes-prod"
APP_SECRET = "mes-secret-change-me"

PAYLOADS = {
    # 完工入库：生成一张待入库的产品入库单
    "production": ("/integration/production-inbound", {
        "no": f"PI{time.strftime('%Y%m%d')}901", "version": 1,
        "task_no": "RWD20261110901", "box_code": "BOX20261110DEMO001",
        "product_code": "A3288", "qty": 30,
    }),
    # 销售发货：生成一张待出库的销售出库单
    "outbound": ("/integration/outbound-orders", {
        "no": f"SO{time.strftime('%Y%m%d')}901", "version": 1,
        "sales_order_no": "XSDD20261110901", "product_code": "A3288",
        "plan_qty": 10, "delivery_date": time.strftime("%Y-%m-%d"),
    }),
    # 领料需求：生成一张待出库的领料单
    "pick": ("/integration/pick-requests", {
        "no": f"PL{time.strftime('%Y%m%d')}901", "version": 1,
        "task_no": "RWD20261110901",
        "items": [{"material_code": "BAT-LIPO-4500-003", "qty": 50}],
    }),
}


def push(url: str, kind: str) -> dict:
    path, payload = PAYLOADS[kind]
    body = json.dumps(payload, ensure_ascii=False).encode()
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-App-Key": APP_KEY,
        "X-Timestamp": ts,
        "X-Sign": sign(APP_SECRET, APP_KEY, ts, body),
    }
    req = urllib.request.Request(f"{url}{path}", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/api/v1")
    ap.add_argument("--kind", default="production", choices=sorted(PAYLOADS))
    args = ap.parse_args()

    res = push(args.url, args.kind)
    print(f"[{args.kind}] -> {res.get('code')} {res.get('message')}")
    if res.get("data"):
        print("  ", res["data"])
    if res.get("code") == "WMS-4091":
        print("   （同一单号重复推送，返回首次结果——这就是幂等）")
    return 0 if res.get("code") in ("0", "WMS-4091") else 1


if __name__ == "__main__":
    sys.exit(main())
