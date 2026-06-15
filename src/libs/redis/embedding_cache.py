"""Embedding Semantic Cache backed by Redis.

Caches the embedding vector for a given text so repeated queries or chunks
with identical content only call the embedding API once.

Key format: ``rag:embedding:<sha256_hash_of_text>``

Hash strategy: SHA-256 of the raw text (fast, deterministic, no collisions
across the 16-character prefix, while the full hash is stored as the value).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Dict, List, Optional, Tuple

from src.core.settings import RedisSettings, RedisTTLSettings
from src.libs.redis.client import BaseCache, get_redis_client
from src.observability.logger import get_logger

logger = get_logger(__name__)

_Stats = Dict[str, int]


class EmbeddingCache:
    """Redis-backed semantic cache for embedding vectors.

    On construction the TTL is taken from ``settings.redis.ttl.embedding``.
    When Redis is unavailable the cache gracefully degrades to a no-op
    (all lookups miss) so the calling code never breaks.

    Thread-safe: all Redis operations are atomic.
    """

    _KEY_PREFIX = "embedding"

    def __init__(
        self,
        settings: Optional[RedisSettings] = None,
        ttl: Optional[int] = None,
    ) -> None:
        self._ttl = ttl or 604800
        self._client = get_redis_client(settings)
        self._stats: _Stats = {"hits": 0, "misses": 0, "errors": 0}

    @property
    def stats(self) -> _Stats:
        return self._stats.copy()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, text: str) -> Optional[List[float]]:
        """Return cached embedding vector for *text*, or None on miss."""
        try:
            key = self._key_for_text(text)
            raw = self._client.get(key)
            if raw is None:
                self._stats["misses"] += 1
                return None
            self._stats["hits"] += 1
            return json.loads(raw)
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"EmbeddingCache.get failed: {e}")
            return None

    def set(self, text: str, vector: List[float]) -> bool:
        """Cache *vector* for *text*. Returns True on success."""
        try:
            key = self._key_for_text(text)
            ok = self._client.set(key, json.dumps(vector), ex=self._ttl)
            return bool(ok)
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"EmbeddingCache.set failed: {e}")
            return False

    def get_many(
        self, texts: List[str]
    ) -> Tuple[List[Optional[List[float]]], List[Tuple[int, str]]]:
        """Batch lookup: returns (cached_vectors, [(index, text), ...] for misses).

        The caller should embed the misses and then call :meth:`set_many`.
        """
        if not texts:
            return [], []

        hits: List[Optional[List[float]]] = [None] * len(texts)
        miss_indices: List[Tuple[int, str]] = []

        # DummyRedis pipeline returns bools, not strings — handle directly
        from src.libs.redis.client import _DummyRedis
        if isinstance(self._client, _DummyRedis):
            for idx, text in enumerate(texts):
                raw = self._client.get(self._key_for_text(text))
                if raw is None:
                    miss_indices.append((idx, text))
                    self._stats["misses"] += 1
                else:
                    self._stats["hits"] += 1
                    hits[idx] = json.loads(raw) if isinstance(raw, str) else None
            return hits, miss_indices

        try:
            pipe = self._client.pipeline()
            for text in texts:
                pipe.get(self._key_for_text(text))
            raw_results = pipe.execute()
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"EmbeddingCache.get_many pipeline failed: {e}")
            return [None] * len(texts), list(enumerate(texts))

        for idx, raw in enumerate(raw_results):
            if raw is None:
                miss_indices.append((idx, texts[idx]))
                self._stats["misses"] += 1
            else:
                try:
                    hits[idx] = json.loads(raw)
                    self._stats["hits"] += 1
                except (json.JSONDecodeError, TypeError):
                    miss_indices.append((idx, texts[idx]))
                    self._stats["misses"] += 1

        return hits, miss_indices

    def set_many(self, items: List[Tuple[str, List[float]]]) -> int:
        """Batch write: items is a list of (text, vector). Returns success count."""
        if not items:
            return 0

        count = 0
        try:
            pipe = self._client.pipeline()
            for text, vector in items:
                pipe.setex(self._key_for_text(text), self._ttl, json.dumps(vector))
            results = pipe.execute()
            count = sum(1 for r in results if r)
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"EmbeddingCache.set_many failed: {e}")

        return count

    def clear(self) -> int:
        """Remove all cached embeddings. Returns number of keys deleted."""
        try:
            pattern = f"rag:{self._KEY_PREFIX}:*"
            keys = self._client.keys(pattern)
            if keys:
                return self._client.delete(*keys)
            return 0
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"EmbeddingCache.clear failed: {e}")
            return 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key_for_text(text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
        return f"rag:embedding:{digest}"
