# -*- coding: utf-8 -*-
"""pytest 公共配置。

默认用 SQLite 文件库跑全量用例（零外部依赖，CI 可直接跑）；
需要真行锁的用例打 `requires_mysql` 标记，只有 DB_URL 指向 MySQL 时才执行。
"""
from __future__ import annotations

import os

os.environ.setdefault("DB_URL", "sqlite:///./test_wms.db")
# AI 走只读连接，测试里必须也指到同一个库——否则会连到 .env 里的 MySQL 只读账号，
# 而那个库里没有测试表
os.environ.setdefault("DB_READONLY_URL", os.environ["DB_URL"])
os.environ.setdefault("WMS_REDIS_MEMORY", "1")

import pytest  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.core.db import SessionLocal, create_all, drop_all, engine  # noqa: E402
from app.core.redis import rds  # noqa: E402
from app.domain.models import Base  # noqa: E402

IS_MYSQL = engine.dialect.name == "mysql"


def _truncate_all() -> None:
    """清空所有表数据（保留表结构），按依赖逆序删。"""
    with engine.begin() as c:
        prep = c.dialect.identifier_preparer
        for t in reversed(Base.metadata.sorted_tables):
            c.execute(text(f"DELETE FROM {prep.quote(t.name)}"))


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_mysql: 需要真实行锁，只在 MySQL 下运行")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """整个 session 只建/删一次表结构，用例之间只清数据——快 20 倍。"""
    drop_all()
    create_all()
    yield
    drop_all()
    try:
        os.remove("test_wms.db")
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _clean_data():
    _truncate_all()
    rds._mem._d.clear()  # noqa: SLF001
    yield
    _truncate_all()


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def seeded(db):
    """灌种子数据，返回种子 session。"""
    from app.seed import seed

    seed(db)
    return db


@pytest.fixture
def client(seeded):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def _captcha_code(client, captcha_id: str) -> str:
    """测试专用：从进程内 Redis 直接取验证码明文。"""
    return rds.get(f"captcha:{captcha_id}")


def login(client, username: str) -> dict:
    """登录并返回带 Bearer 的 header 字典（种子账号密码同名）。"""
    cap = client.get("/api/v1/auth/captcha").json()["data"]
    r = client.post("/api/v1/auth/login", json={
        "username": username, "password": username,
        "captcha_id": cap["captcha_id"],
        "captcha": _captcha_code(client, cap["captcha_id"]),
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == "0", body
    return {"Authorization": f"Bearer {body['data']['access_token']}"}


@pytest.fixture
def admin_token(client):
    return login(client, "admin")


@pytest.fixture
def login_as(client):
    return lambda username: login(client, username)


@pytest.fixture
def mysql_only():
    if not IS_MYSQL:
        pytest.skip("需要 MySQL 行锁，当前后端为 " + engine.dialect.name)


@pytest.fixture
def wh1_id(seeded):
    """WH-001 的 id。不能写死 1——MySQL 的自增不会随 drop/create 归零。"""
    from app.domain.models import Warehouse

    return seeded.execute(
        select(Warehouse.id).where(Warehouse.code == "WH-001")
    ).scalar_one()


@pytest.fixture
def admin_id(seeded):
    from app.domain.models import User

    return seeded.execute(select(User.id).where(User.username == "admin")).scalar_one()


@pytest.fixture
def wh1_location_id(seeded, wh1_id):
    """WH-001 下任意一个库位的 id。注意别拿仓库 id 当库位 id用——
    SQLite 重建表后两者恰好对齐，MySQL 的自增不归零，会静默跑错。"""
    from app.domain.models import Location

    return seeded.execute(
        select(Location.id).where(Location.warehouse_id == wh1_id)
    ).scalars().first()


@pytest.fixture
def wh2_id(seeded):
    from app.domain.models import Warehouse

    return seeded.execute(
        select(Warehouse.id).where(Warehouse.code == "WH-002")
    ).scalar_one()


@pytest.fixture
def wh3_id(seeded):
    from app.domain.models import Warehouse

    return seeded.execute(
        select(Warehouse.id).where(Warehouse.code == "WH-003")
    ).scalar_one()
