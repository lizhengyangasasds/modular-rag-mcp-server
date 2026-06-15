"""LLM Response Cache backed by Redis.

Caches LLM-generated results (chunk refinement, metadata enrichment) so that
identical prompts sent to the same LLM do not count against rate limits or cost.

Key format: ``rag:llm:<sha256_hash_of_prompt_and_input>``

The cache key is built from a hash of:
  - The prompt template (for ChunkRefiner or MetadataEnricher)
  - The input text/chunk being processed
This ensures that the same content always hits the cache regardless of
session, timing, or which Pipeline instance processed it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Optional, Tuple

from src.core.settings import RedisSettings
from src.libs.redis.client import get_redis_client
from src.observability.logger import get_logger

logger = get_logger(__name__)

_Stats = Dict[str, int]


class LLMResponseCache:
    """Redis-backed cache for LLM responses.

    Gracefully degrades to a no-op when Redis is unavailable.
    Thread-safe for concurrent access.
    """

    _KEY_PREFIX = "llm"

    def __init__(
        self,
        settings: Optional[RedisSettings] = None,
        ttl: Optional[int] = None,
    ) -> None:
        self._ttl = ttl or 86400
        self._client = get_redis_client(settings)
        self._stats: _Stats = {"hits": 0, "misses": 0, "errors": 0}

    @property
    def stats(self) -> _Stats:
        return self._stats.copy()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, prompt_template: str, input_text: str) -> Optional[str]:
        """Return cached LLM response for the given prompt+input pair, or None."""
        try:
            key = self._key(prompt_template, input_text)
            raw = self._client.get(key)
            if raw is None:
                self._stats["misses"] += 1
                return None
            self._stats["hits"] += 1
            return raw
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"LLMResponseCache.get failed: {e}")
            return None

    def set(self, prompt_template: str, input_text: str, response: str) -> bool:
        """Cache a (prompt_template, input_text) → response mapping."""
        try:
            key = self._key(prompt_template, input_text)
            return bool(self._client.set(key, response, ex=self._ttl))
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"LLMResponseCache.set failed: {e}")
            return False

    def get_metadata(
        self, prompt_template: str, input_text: str
    ) -> Optional[Dict[str, Any]]:
        """Return cached structured metadata dict, or None."""
        try:
            key = self._key(prompt_template, input_text)
            raw = self._client.get(key)
            if raw is None:
                self._stats["misses"] += 1
                return None
            self._stats["hits"] += 1
            return json.loads(raw)
        except json.JSONDecodeError:
            self._stats["misses"] += 1
            return None
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"LLMResponseCache.get_metadata failed: {e}")
            return None

    def set_metadata(
        self,
        prompt_template: str,
        input_text: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """Cache a structured metadata dict result."""
        try:
            key = self._key(prompt_template, input_text)
            return bool(self._client.set(key, json.dumps(metadata), ex=self._ttl))
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"LLMResponseCache.set_metadata failed: {e}")
            return False

    def invalidate(self, prompt_template: str, input_text: str) -> bool:
        """Remove a single cache entry."""
        try:
            key = self._key(prompt_template, input_text)
            return bool(self._client.delete(key))
        except Exception as e:
            logger.warning(f"LLMResponseCache.invalidate failed: {e}")
            return False

    def clear(self) -> int:
        """Remove all cached LLM responses. Returns count of deleted keys."""
        try:
            pattern = f"rag:{self._KEY_PREFIX}:*"
            keys = self._client.keys(pattern)
            if keys:
                return self._client.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"LLMResponseCache.clear failed: {e}")
            return 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(prompt_template: str, input_text: str) -> str:
        combined = f"{prompt_template}|||{input_text}"
        digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:32]
        return f"rag:llm:{digest}"
