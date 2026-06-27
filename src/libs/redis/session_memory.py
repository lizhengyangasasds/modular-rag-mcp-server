"""Session Memory backed by Redis.

Provides conversation history persistence and last-result caching for multi-turn
query sessions. Each session is stored as a Redis Hash.

Key format: ``rag:session:<session_id>``

Fields per session:
  - history: JSON-encoded list of (role, content) message tuples
  - last_query: the most recent user query string
  - last_results: JSON-encoded list of RetrievalResult dicts
  - created_at: Unix timestamp of session creation
  - updated_at: Unix timestamp of last update

TTL is refreshed on every access (sliding expiry).
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.core.settings import RedisSettings
from src.libs.redis.client import get_redis_client
from src.observability.logger import get_logger

logger = get_logger(__name__)


class SessionMemory:
    """Redis-backed session memory for multi-turn RAG conversations.

    Gracefully degrades when Redis is unavailable (all operations become no-ops).

    Thread-safe: uses Redis HSET/EXPIRE which are atomic per key.
    """

    _KEY_PREFIX = "session"

    def __init__(
        self,
        settings: RedisSettings | None = None,
        ttl: int | None = None,
    ) -> None:
        self._ttl = ttl or 3600
        self._client = get_redis_client(settings)
        self._stats: dict[str, int] = {"hits": 0, "misses": 0, "errors": 0}

    @property
    def stats(self) -> dict[str, int]:
        return self._stats.copy()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def get_or_create(self, session_id: str) -> dict[str, Any]:
        """Return existing session data or create a new empty one.

        Calling this method also refreshes the TTL (sliding window).
        """
        key = self._key(session_id)
        try:
            data = self._client.hgetall(key)
            if data:
                self._stats["hits"] += 1
                self._refresh_ttl(key)
                return {
                    "session_id": session_id,
                    "history": json.loads(data.get("history", "[]")),
                    "last_query": data.get("last_query", ""),
                    "last_results": json.loads(data.get("last_results", "[]")),
                    "created_at": float(data.get("created_at", time.time())),
                    "updated_at": float(data.get("updated_at", time.time())),
                }
            else:
                self._stats["misses"] += 1
                now = time.time()
                self._client.hset(key, mapping={
                    "history": "[]",
                    "last_query": "",
                    "last_results": "[]",
                    "created_at": str(now),
                    "updated_at": str(now),
                })
                self._client.expire(key, self._ttl)
                return {
                    "session_id": session_id,
                    "history": [],
                    "last_query": "",
                    "last_results": [],
                    "created_at": now,
                    "updated_at": now,
                }
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"SessionMemory.get_or_create failed for {session_id}: {e}")
            return {"session_id": session_id, "history": [], "last_query": "", "last_results": [], "created_at": time.time(), "updated_at": time.time()}

    def delete(self, session_id: str) -> bool:
        """Delete a session and its data."""
        try:
            return bool(self._client.delete(self._key(session_id)))
        except Exception as e:
            logger.warning(f"SessionMemory.delete failed for {session_id}: {e}")
            return False

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> bool:
        """Append a message to the session history.

        Args:
            session_id: Unique session identifier
            role: "user" or "assistant"
            content: Message text

        Returns:
            True on success.
        """
        try:
            key = self._key(session_id)
            history_raw = self._client.hget(key, "history") or "[]"
            history = json.loads(history_raw)
            history.append({"role": role, "content": content})
            self._client.hset(key, mapping={
                "history": json.dumps(history),
                "updated_at": str(time.time()),
            })
            self._client.expire(key, self._ttl)
            return True
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"SessionMemory.add_message failed: {e}")
            return False

    def get_history(self, session_id: str, limit: int = 20) -> list[dict[str, str]]:
        """Return the last *limit* messages from session history."""
        try:
            key = self._key(session_id)
            history_raw = self._client.hget(key, "history") or "[]"
            history: list[dict[str, str]] = json.loads(history_raw)
            self._refresh_ttl(key)
            return history[-limit:]
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"SessionMemory.get_history failed: {e}")
            return []

    def get_full_history(self, session_id: str) -> list[dict[str, str]]:
        """Return the complete session history."""
        return self.get_history(session_id, limit=999999)

    # ------------------------------------------------------------------
    # Last query / results (for context in next turn)
    # ------------------------------------------------------------------

    def set_last_query(self, session_id: str, query: str) -> bool:
        """Store the most recent user query."""
        try:
            key = self._key(session_id)
            self._client.hset(key, mapping={
                "last_query": query,
                "updated_at": str(time.time()),
            })
            self._client.expire(key, self._ttl)
            return True
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"SessionMemory.set_last_query failed: {e}")
            return False

    def get_last_query(self, session_id: str) -> str | None:
        """Return the most recent user query, or None."""
        try:
            key = self._key(session_id)
            val = self._client.hget(key, "last_query")
            self._refresh_ttl(key)
            return val if val else None
        except Exception:
            self._stats["errors"] += 1
            return None

    def set_last_results(
        self,
        session_id: str,
        results: list[dict[str, Any]],
    ) -> bool:
        """Cache the last retrieval results for potential re-ranking / reuse."""
        try:
            key = self._key(session_id)
            self._client.hset(key, mapping={
                "last_results": json.dumps(results),
                "updated_at": str(time.time()),
            })
            self._client.expire(key, self._ttl)
            return True
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"SessionMemory.set_last_results failed: {e}")
            return False

    def get_last_results(self, session_id: str) -> list[dict[str, Any]]:
        """Return the last retrieval results, or an empty list."""
        try:
            key = self._key(session_id)
            raw = self._client.hget(key, "last_results") or "[]"
            self._refresh_ttl(key)
            return json.loads(raw)
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"SessionMemory.get_last_results failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Session listing (admin / debug)
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[str]:
        """Return all active session IDs."""
        try:
            pattern = f"rag:{self._KEY_PREFIX}:*"
            keys = self._client.keys(pattern)
            prefix = f"rag:{self._KEY_PREFIX}:"
            return [k.removeprefix(prefix) for k in keys]
        except Exception as e:
            logger.warning(f"SessionMemory.list_sessions failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _key(self, session_id: str) -> str:
        return f"rag:{self._KEY_PREFIX}:{session_id}"

    def _refresh_ttl(self, key: str) -> None:
        """Sliding expiry refresh. Best-effort: failures are logged but not raised.

        Redis TTL refresh is a non-critical optimization; if it fails the
        session still works, it just expires sooner. We log so operators can
        spot Redis instability without crashes masking it.
        """
        try:
            self._client.expire(key, self._ttl)
        except Exception as exc:
            logger.debug("Redis TTL refresh failed for key=%s: %s", key, exc)
