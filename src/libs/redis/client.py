"""Redis client singleton and base cache layer.

Provides a lazily-initialized, thread-safe Redis connection pool and a
thin base class that all cache implementations inherit from.
"""

from __future__ import annotations

import threading
from typing import Any

import redis

from src.core.settings import RedisSettings
from src.observability.logger import get_logger

logger = get_logger(__name__)

_redis_client: redis.Redis | None = None
_redis_lock = threading.Lock()


def get_redis_client(settings: RedisSettings | None = None) -> redis.Redis:
    """Return a global Redis client (singleton pattern, thread-safe).

    If Redis is disabled or unreachable, a dummy client that never blocks
    is returned so the rest of the codebase stays unaffected.

    Args:
        settings: Redis configuration. If None, falls back to defaults.

    Returns:
        A redis.Redis instance (or a no-op dummy if unavailable).
    """
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    with _redis_lock:
        if _redis_client is not None:
            return _redis_client

        cfg = settings
        if cfg is None or not cfg.enabled:
            logger.info("Redis cache disabled (settings.redis.enabled=False)")
            _redis_client = _DummyRedis()
            return _redis_client

        try:
            pool = redis.ConnectionPool(
                host=cfg.host,
                port=cfg.port,
                db=cfg.db,
                password=cfg.password,
                max_connections=20,
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                retry_on_timeout=True,
            )
            client = redis.Redis(connection_pool=pool)
            client.ping()
            logger.info(
                f"Redis connected: {cfg.host}:{cfg.port}/{cfg.db}"
            )
            _redis_client = client
        except redis.RedisError as e:
            logger.warning(f"Redis unavailable ({e}), caching disabled.")
            _redis_client = _DummyRedis()

    return _redis_client


def close_redis_client() -> None:
    """Close the global Redis connection pool (used at application shutdown)."""
    global _redis_client
    with _redis_lock:
        if _redis_client is not None and not isinstance(_redis_client, _DummyRedis):
            _redis_client.close()
        _redis_client = None


class _DummyRedis:
    """No-op Redis stand-in used when Redis is unavailable.

    All public methods are no-ops that return None / False / empty so
    callers can guard with ``if cache.get(...)`` without raising.
    """

    def ping(self) -> bool:
        return False

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        return True

    def setex(self, key: str, time: int, value: str) -> bool:
        return True

    def delete(self, *keys: str) -> int:
        return 0

    def exists(self, key: str) -> int:
        return 0

    def hset(self, name: str, mapping: dict[str, str] | None = None, **kwargs: Any) -> int:
        return 0

    def hget(self, name: str, key: str) -> str | None:
        return None

    def hgetall(self, name: str) -> dict[str, str]:
        return {}

    def expire(self, name: str, time: int) -> bool:
        return False

    def keys(self, pattern: str) -> list[str]:
        return []

    def close(self) -> None:
        pass

    def pipeline(self) -> _DummyPipeline:
        return _DummyPipeline()


class _DummyPipeline:
    def __init__(self) -> None:
        self._commands: list[Any] = []

    def __getitem__(self, key: str) -> _DummyPipeline:
        self._commands.append(("get", key))
        return self

    def __setitem__(self, key: str, value: Any) -> _DummyPipeline:
        self._commands.append(("set", key, value))
        return self

    def get(self, key: str) -> _DummyPipeline:
        self._commands.append(("get", key))
        return self

    def setex(self, key: str, time: int, value: str) -> _DummyPipeline:
        self._commands.append(("setex", key, time, value))
        return self

    def execute(self) -> list[Any]:
        return [True] * len(self._commands)

    def __enter__(self) -> _DummyPipeline:
        return self

    def __exit__(self, *_: Any) -> None:
        pass


class BaseCache:
    """Thin base class shared by all cache implementations.

    Provides common key-building utilities and delegates the actual
    Redis read/write to the global client.
    """

    KEY_PREFIX: str = "rag"

    def __init__(self, ttl: int, key_prefix: str | None = None) -> None:
        self.ttl = ttl
        if key_prefix:
            self.KEY_PREFIX = key_prefix
        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = get_redis_client()
        return self._client

    def _make_key(self, *parts: Any) -> str:
        return ":".join([self.KEY_PREFIX] + [str(p) for p in parts])

    def get(self, key: str) -> str | None:
        try:
            return self.client.get(key)
        except redis.RedisError as e:
            logger.warning(f"Redis GET failed on {key}: {e}")
            return None

    def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        try:
            effective_ttl = ttl if ttl is not None else self.ttl
            return bool(self.client.set(key, value, ex=effective_ttl))
        except redis.RedisError as e:
            logger.warning(f"Redis SET failed on {key}: {e}")
            return False

    def delete(self, key: str) -> bool:
        try:
            return bool(self.client.delete(key))
        except redis.RedisError as e:
            logger.warning(f"Redis DELETE failed on {key}: {e}")
            return False

    def exists(self, key: str) -> bool:
        try:
            return bool(self.client.exists(key))
        except redis.RedisError as e:
            logger.warning(f"Redis EXISTS failed on {key}: {e}")
            return False

    def clear_prefix(self, prefix: str) -> int:
        """Delete all keys matching ``{KEY_PREFIX}:{prefix}*``."""
        try:
            pattern = self._make_key(prefix, "*")
            keys = self.client.keys(pattern)
            if keys:
                return self.client.delete(*keys)
            return 0
        except redis.RedisError as e:
            logger.warning(f"Redis CLEAR_PREFIX failed for {prefix}: {e}")
            return 0
