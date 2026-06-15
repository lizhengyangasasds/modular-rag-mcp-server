"""Redis caching layer for Modular RAG MCP Server.

Provides three independent cache types:
- :class:`EmbeddingCache`: caches embedding vectors keyed by text hash.
- :class:`LLMResponseCache`: caches LLM responses (refinement / enrichment).
- :class:`SessionMemory`: persists multi-turn conversation history.

All caches gracefully degrade to no-ops when Redis is unavailable.
"""

from src.libs.redis.client import (
    BaseCache,
    close_redis_client,
    get_redis_client,
)
from src.libs.redis.embedding_cache import EmbeddingCache
from src.libs.redis.llm_response_cache import LLMResponseCache
from src.libs.redis.session_memory import SessionMemory

__all__ = [
    "EmbeddingCache",
    "LLMResponseCache",
    "SessionMemory",
    "get_redis_client",
    "close_redis_client",
    "BaseCache",
]
