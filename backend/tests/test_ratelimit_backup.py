# -*- coding: utf-8 -*-
"""限流与备份任务测试。"""
from __future__ import annotations

import gzip
import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.redis import rds
from app.middleware import ratelimit
from tests.conftest import login


def _post(client, path, headers, json=None):
    return client.post(path, headers={**headers, "X-Client-Op-Id": str(uuid.uuid4())},
                       json=json)


@pytest.fixture
def ah(client):
    return login(client, "admin")


# ---------------------------------------------------------------- 限流
def test_写接口超过上限返回429(seeded, client, ah, monkeypatch):
    monkeypatch.setattr(settings, "rl_write", 3)
    codes = []
    for i in range(5):
        r = _post(client, "/api/v1/warehouses", ah,
                  {"code": f"WH-RL-{i}", "name": f"限流{i}", "type": "AUX"})
        codes.append(r.status_code)
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429 and codes[4] == 429

    body = _post(client, "/api/v1/warehouses", ah,
                 {"code": "WH-RL-X", "name": "x", "type": "AUX"}).json()
    assert body["code"] == "WMS-4290"
    assert body["data"]["bucket"] == "write"


def test_读接口不受写限流影响(seeded, client, ah, monkeypatch):
    monkeypatch.setattr(settings, "rl_write", 1)
    for _ in range(3):
        assert client.get("/api/v1/warehouses", headers=ah).status_code == 200


def test_同步补传单独限流(seeded, client, ah, monkeypatch):
    monkeypatch.setattr(settings, "rl_sync_push", 2)
    codes = []
    for _ in range(3):
        r = _post(client, "/api/v1/sync/push", ah, {"ops": [{
            "client_op_id": str(uuid.uuid4()), "op_type": "INBOUND_SCAN",
            "path": "/x", "body": {"order_id": 1}, "created_at": None}]})
        codes.append(r.status_code)
    assert codes[2] == 429, codes


def test_登录与健康检查不限流(seeded, client, monkeypatch):
    monkeypatch.setattr(settings, "rl_write", 0)
    for _ in range(3):
        assert client.get("/api/v1/auth/captcha").status_code == 200
        assert client.get("/health").status_code == 200


def test_限流桶按身份区分(seeded, client, ah, monkeypatch):
    """别人打满不影响我。"""
    monkeypatch.setattr(settings, "rl_write", 1)
    keeper = login(client, "wangjf")
    assert _post(client, "/api/v1/warehouses", ah,
                 {"code": "WH-A", "name": "a", "type": "AUX"}).status_code == 200
    # admin 已被 admin 自己打满
    assert _post(client, "/api/v1/warehouses", ah,
                 {"code": "WH-B", "name": "b", "type": "AUX"}).status_code == 429
    # 仓管员是另一个桶（虽然它没权限，也是 403 而不是 429）
    r = _post(client, "/api/v1/warehouses", keeper,
              {"code": "WH-C", "name": "c", "type": "AUX"})
    assert r.status_code == 403


def test_桶函数按路径归类():
    class Req:
        def __init__(self, path, method="POST"):
            self.url = type("U", (), {"path": path})()
            self.method = method
            self.headers = {}

    from app.core.config import settings as st

    assert ratelimit._bucket(Req(f"{st.api_prefix}/integration/outbound-orders"))[0] == "integration"
    assert ratelimit._bucket(Req(f"{st.api_prefix}/sync/push"))[0] == "sync"
    assert ratelimit._bucket(Req(f"{st.api_prefix}/ai/query"))[0] == "aiquery"
    assert ratelimit._bucket(Req(f"{st.api_prefix}/warehouses"))[0] == "write"
    assert ratelimit._bucket(Req(f"{st.api_prefix}/warehouses", "GET")) is None


# ---------------------------------------------------------------- 备份
def test_备份找不到mysqldump时只记错误不抛(monkeypatch, tmp_path):
    from app.tasks import backup

    monkeypatch.setattr(backup, "_find_dump", lambda: None)
    r = backup.run(out_dir=str(tmp_path))
    assert r["ok"] is False and "not found" in r["reason"]


def test_备份在非MySQL后端时跳过(monkeypatch, tmp_path):
    from app.tasks import backup

    monkeypatch.setattr(backup, "_find_dump", lambda: "/usr/bin/mysqldump")
    monkeypatch.setattr(settings, "db_url", "sqlite:///./x.db")
    r = backup.run(out_dir=str(tmp_path))
    assert r["ok"] is False and r["reason"] == "not mysql"


def test_备份成功写出压缩文件并轮转(monkeypatch, tmp_path, capsys):
    """用假的 mysqldump 脚本验证：写 gz、大小、旧文件清理。"""
    from app.tasks import backup

    # 不写真实的 shell 脚本：Windows 上 subprocess 跑不了 shebang，直接打桩
    class _P:
        returncode = 0
        stdout = b"CREATE TABLE t (id INT);"
        stderr = b""

    monkeypatch.setattr(backup, "_find_dump", lambda: "mysqldump")
    monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: _P())
    monkeypatch.setattr(settings, "db_url", "mysql+pymysql://u:p@127.0.0.1:3306/wms")

    # 造一个 8 天前的旧备份，应被清掉
    old = tmp_path / "wms-20000101-0000.sql.gz"
    with gzip.open(old, "wb") as f:
        f.write(b"old")
    import os
    from datetime import datetime, timedelta
    stamp = (datetime.now() - timedelta(days=8)).timestamp()
    os.utime(old, (stamp, stamp))

    r = backup.run(out_dir=str(tmp_path))
    assert r["ok"] is True, r
    assert Path(r["file"]).exists()
    with gzip.open(r["file"], "rb") as f:
        assert b"CREATE TABLE" in f.read()
    assert r["removed"] == 1
    assert not old.exists()


def test_备份解析带特殊字符的连接串():
    from app.tasks.backup import _parse_db_url

    c = _parse_db_url("mysql+pymysql://u%40x:p%23w@db:3307/wms?charset=utf8mb4")
    assert c["user"] == "u@x" and c["password"] == "p#w"
    assert c["port"] == "3307" and c["db"] == "wms"
