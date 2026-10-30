"""Redis 客户端。连不上时退化到进程内实现，保证本地无 Redis 也能跑通开发与单测。

ponytail: 进程内兜底不跨 worker/多机共享。生产必须配真 Redis（compose 已含），
退化仅限本地开发与 CI；需要分布式一致性时删掉 _MemRedis 分支即可。
"""
from __future__ import annotations

import os
import threading
import time

from app.core.config import settings

# 测试/CI 用：置 1 时强制进程内实现，不尝试连真 Redis
_FORCE_MEMORY = os.getenv("WMS_REDIS_MEMORY") == "1"

try:  # pragma: no cover - 依赖缺失只在未装 redis 包时发生
    import redis as _redis

    _HAS_REDIS = True
except Exception:  # pragma: no cover
    _HAS_REDIS = False


class _MemRedis:
    """只实现本项目用到的几个原语：set(nx/ex)、get、delete、exists、incr、expire。"""

    def __init__(self) -> None:
        self._d: dict[str, tuple[str, float | None]] = {}
        self._lock = threading.RLock()  # 可重入：incr 内部会调 get

    def _alive(self, k: str) -> bool:
        item = self._d.get(k)
        if item is None:
            return False
        _, exp = item
        if exp is not None and exp <= time.time():
            self._d.pop(k, None)
            return False
        return True

    def set(self, name, value, nx=False, ex=None):  # noqa: A002
        with self._lock:
            if nx and self._alive(name):
                return None
            self._d[name] = (self._enc(value), time.time() + ex if ex else None)
            return True

    def get(self, name):
        with self._lock:
            if not self._alive(name):
                return None
            return self._d[name][0]

    def delete(self, *names):
        with self._lock:
            return sum(1 for n in names if self._d.pop(n, None) is not None)

    def exists(self, *names):
        with self._lock:
            return sum(1 for n in names if self._alive(n))

    def incr(self, name):
        with self._lock:
            v = int(self.get(name) or 0) + 1
            self._d[name] = (self._enc(v), None)
            return v

    def expire(self, name, seconds):
        with self._lock:
            if not self._alive(name):
                return False
            v, _ = self._d[name]
            self._d[name] = (v, time.time() + seconds)
            return True

    @staticmethod
    def _enc(v) -> str:
        """与真客户端的 decode_responses=True 保持一致：一律返回 str。"""
        return v if isinstance(v, str) else str(v)


class _Client:
    """统一门面：真 Redis 与进程内实现同一套方法签名。"""

    def __init__(self) -> None:
        self._real = None
        self._mem = _MemRedis()
        self._tried = False

    def _connect(self):
        if self._tried or _FORCE_MEMORY:
            return self._real
        self._tried = True
        if _HAS_REDIS:
            try:
                c = _redis.Redis.from_url(
                    settings.redis_url, decode_responses=True, socket_connect_timeout=1
                )
                c.ping()
                self._real = c
            except Exception:
                self._real = None
        return self._real

    def __getattr__(self, item):
        real = self._connect()
        if real is not None:
            return getattr(real, item)
        return getattr(self._mem, item)

    @property
    def backend(self) -> str:
        return "redis" if self._connect() is not None else "memory"


rds = _Client()
