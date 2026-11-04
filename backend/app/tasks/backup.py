"""每日备份（T-05-9 / 架构 10）。由 APScheduler 在 03:00 调用，也可手工跑。

单机部署没有主从，每日全量备份是唯一的数据保护手段。
用 mysqldump 而不是 Python 导出：一致性（--single-transaction）和恢复路径都更可靠。

找不到 mysqldump 时只记 ERROR 不抛异常——备份失败不该把调度进程带崩，
但日志必须是 ERROR 级别，让告警抓得到。
"""
from __future__ import annotations

import gzip
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("wms.backup")

KEEP_DAYS = 7


def _parse_db_url(url: str) -> dict:
    u = urlparse(url)
    return {
        "host": u.hostname or "127.0.0.1",
        "port": str(u.port or 3306),
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "db": (u.path or "/wms").lstrip("/"),
    }


def _find_dump() -> str | None:
    env = os.getenv("MYSQLDUMP_BIN")
    if env and Path(env).exists():
        return env
    return shutil.which("mysqldump")


def run(*, out_dir: str | None = None, keep_days: int = KEEP_DAYS) -> dict:
    target = Path(out_dir or settings.backup_dir)
    dump = _find_dump()
    if dump is None:
        log.error("backup skipped: 找不到 mysqldump（设 MYSQLDUMP_BIN 或在镜像里装 mysql-client）")
        return {"ok": False, "reason": "mysqldump not found"}

    if not settings.db_url.startswith("mysql"):
        log.error("backup skipped: 当前 DB_URL 不是 MySQL（%s）", settings.db_url.split(":")[0])
        return {"ok": False, "reason": "not mysql"}

    conf = _parse_db_url(settings.db_url)
    target.mkdir(parents=True, exist_ok=True)
    out = target / f"wms-{datetime.now():%Y%m%d-%H%M}.sql.gz"

    cmd = [
        dump, f"--host={conf['host']}", f"--port={conf['port']}",
        f"--user={conf['user']}", f"--password={conf['password']}",
        "--single-transaction", "--quick", "--routines", "--triggers",
        "--set-gtid-purged=OFF", conf["db"],
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=1800, check=False)
        if proc.returncode != 0:
            # 密码错误等会走这里；stdout 是数据，错误在 stderr
            log.error("backup failed rc=%s: %s", proc.returncode,
                      proc.stderr.decode("utf-8", "ignore")[:300])
            return {"ok": False, "reason": f"mysqldump rc={proc.returncode}"}
        with gzip.open(out, "wb") as f:
            f.write(proc.stdout)
    except subprocess.TimeoutExpired:
        log.error("backup timeout after 1800s")
        return {"ok": False, "reason": "timeout"}
    except Exception as e:  # noqa: BLE001
        log.error("backup failed: %s", e)
        return {"ok": False, "reason": str(e)}

    # 轮转：只留最近 N 天
    cutoff = datetime.now().timestamp() - keep_days * 86400
    removed = 0
    for old in target.glob("wms-*.sql.gz"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
            removed += 1

    size = out.stat().st_size
    log.info("backup ok: %s (%.1f MB), 清理 %d 个旧文件", out.name, size / 1e6, removed)
    return {"ok": True, "file": str(out), "bytes": size, "removed": removed}


if __name__ == "__main__":  # pragma: no cover
    print(run())
