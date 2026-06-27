"""Factory for creating Redis-backed cache instances from settings.

Usage::

    from src.libs.redis import EmbeddingCache, LLMResponseCache, SessionMemory
    from src.libs.redis.factory import CacheFactory

    caches = CacheFactory.from_settings(settings)
    caches.embedding.get("hello world")      # → None on first call
    caches.embedding.set("hello world", [0.1, 0.2, ...])

    # or use directly
    from src.libs.redis import EmbeddingCache
    cache = EmbeddingCache(settings=settings.redis)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.libs.redis.embedding_cache import EmbeddingCache
from src.libs.redis.llm_response_cache import LLMResponseCache
from src.libs.redis.session_memory import SessionMemory

if TYPE_CHECKING:
    from src.core.settings import Settings


@dataclass
class CacheBundle:
    """Container for all cache instances (created once per Settings)."""

    embedding: EmbeddingCache
    llm_response: LLMResponseCache
    session: SessionMemory


def create_cache_bundle(
    redis_settings: object | None = None,
    embedding_ttl: int = 604800,
    llm_response_ttl: int = 86400,
    session_ttl: int = 3600,
) -> CacheBundle:
    """Create all three cache instances.

    Args:
        redis_settings: Settings object or dict. If the ``enabled`` field is
            falsy, all caches degrade to no-ops.
        embedding_ttl: TTL for embedding cache entries in seconds.
        llm_response_ttl: TTL for LLM response cache entries.
        session_ttl: TTL for session memory entries (sliding window).

    Returns:
        A CacheBundle with three ready-to-use cache instances.
    """
    # Normalise the settings input so we can accept both a full Settings
    # object and a bare RedisSettings value.
    if redis_settings is not None:
        getattr(redis_settings, "enabled", True)

    embedding_cache = EmbeddingCache(
        settings=redis_settings,
        ttl=embedding_ttl,
    )
    llm_response_cache = LLMResponseCache(
        settings=redis_settings,
        ttl=llm_response_ttl,
    )
    session_memory = SessionMemory(
        settings=redis_settings,
        ttl=session_ttl,
    )

    return CacheBundle(
        embedding=embedding_cache,
        llm_response=llm_response_cache,
        session=session_memory,
    )


def from_settings(settings: Settings) -> CacheBundle:
    """Create a CacheBundle from a fully-loaded Settings object.

    Reads TTL values and the enabled flag from ``settings.redis``.
    When ``settings.redis`` is None or ``enabled=False``, all caches
    become no-ops so the calling code stays unaffected.

    Args:
        settings: A loaded Settings instance.

    Returns:
        A CacheBundle with all three cache types wired up.
    """
    redis_cfg = getattr(settings, "redis", None)
    ttl = redis_cfg.ttl if redis_cfg else None

    return create_cache_bundle(
        redis_settings=redis_cfg,
        embedding_ttl=ttl.embedding if ttl else 604800,
        llm_response_ttl=ttl.llm_response if ttl else 86400,
        session_ttl=ttl.session if ttl else 3600,
    )
