"""数据库引擎。写连接与只读连接分开，只读连接给 AI 模块用（架构 8.1 第一道锁）。"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.domain.models import Base


def _make(url: str, **kw):
    if url.startswith("sqlite"):
        # SQLite（测试用）：文件库 + 允许跨线程用同一连接。
        # 注意不能用 StaticPool 配内存库——那会让多个 Session 共用同一个 DBAPI 连接，
        # 事务状态互相污染。文件库 + QueuePool 才是安全的。
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            future=True,
            **kw,
        )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=kw.pop("pool_size", 10),
        max_overflow=kw.pop("max_overflow", 20),
        pool_recycle=1800,
        future=True,
        **kw,
    )


engine = _make(settings.db_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

# AI 只读连接（架构 8.1 第一道锁）：连的是只授 SELECT 的 wms_ai_ro 账号。
# 留空 DB_READONLY_URL 时退回写连接，仅本地开发可接受——生产必须配，否则三道锁只剩两道。
readonly_engine = _make(settings.readonly_url, pool_size=5, max_overflow=5)
ReadOnlySession = sessionmaker(
    bind=readonly_engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def get_readonly_session() -> Session:
    """AI 模块专用依赖：只给只读 session。"""
    s = ReadOnlySession()
    try:
        yield s
    finally:
        s.close()


def get_session() -> Session:
    """FastAPI 依赖：请求级 session。"""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def create_all() -> None:
    Base.metadata.create_all(engine)


def drop_all() -> None:
    Base.metadata.drop_all(engine)
    if readonly_engine is not engine:
        readonly_engine.dispose()
