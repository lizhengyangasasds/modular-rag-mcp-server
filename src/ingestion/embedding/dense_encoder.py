"""Dense Encoder for generating embeddings from text chunks.

This module implements the Dense Encoder component of the Ingestion Pipeline,
responsible for converting text chunks into dense vector representations using
configurable embedding providers.

Design Principles:
- Config-Driven: Uses factory pattern to obtain embedding provider from settings
- Batch Processing: Optimizes API calls through batching
- Observable: Accepts TraceContext for future observability integration
- Error Handling: Individual failures shouldn't crash entire batch
- Deterministic: Same inputs produce same outputs
- Cache-First: Redis-backed EmbeddingCache avoids repeated API calls
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.types import Chunk
from src.libs.embedding.base_embedding import BaseEmbedding

if TYPE_CHECKING:
    from src.libs.redis.embedding_cache import EmbeddingCache


class DenseEncoder:
    """Encodes text chunks into dense vectors using BaseEmbedding provider.

    This encoder acts as a bridge between the ingestion pipeline and the
    pluggable embedding layer. It handles batching, error recovery, and
    maintains alignment between input chunks and output vectors.

    Design:
    - Dependency Injection: Receives BaseEmbedding instance (no direct factory call)
    - Batch-First: Processes all chunks in configurable batch sizes
    - Stateless: No internal state between encode() calls
    - Cache-First: Optionally wraps embedding calls in EmbeddingCache for
      repeated content (e.g. overlapping chunks from re-ingestion)

    Example:
        >>> from src.libs.embedding.embedding_factory import EmbeddingFactory
        >>> from src.core.settings import load_settings
        >>>
        >>> settings = load_settings("config/settings.yaml")
        >>> embedding = EmbeddingFactory.create(settings)
        >>> encoder = DenseEncoder(embedding, batch_size=32)
        >>>
        >>> chunks = [Chunk(id="1", text="Hello world", metadata={})]
        >>> vectors = encoder.encode(chunks)
        >>> print(len(vectors))  # 1
        >>> print(len(vectors[0]))  # dimension (e.g., 1536)
    """

    def __init__(
        self,
        embedding: BaseEmbedding,
        batch_size: int = 100,
        embedding_cache: EmbeddingCache | None = None,
    ):
        """Initialize DenseEncoder.

        Args:
            embedding: Embedding provider instance (from EmbeddingFactory)
            batch_size: Number of chunks to process per API call (default: 100)

        Raises:
            ValueError: If batch_size <= 0
        """
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size}")

        self.embedding = embedding
        self.batch_size = batch_size
        self._cache = embedding_cache

    @property
    def embedding_cache(self) -> EmbeddingCache | None:
        return self._cache

    def set_embedding_cache(self, cache: EmbeddingCache) -> None:
        self._cache = cache

    def encode(
        self,
        chunks: list[Chunk],
        trace: Any | None = None,
    ) -> list[list[float]]:
        """Encode chunks into dense vectors.

        This method:
        1. Extracts text from each chunk
        2. Batches texts according to batch_size
        3. Calls embedding.embed() for each batch
        4. Concatenates results maintaining chunk order

        Args:
            chunks: List of Chunk objects to encode
            trace: Optional TraceContext for observability (reserved for Stage F)

        Returns:
            List of dense vectors (one per chunk, in same order).
            Each vector is a list of floats with dimension matching the embedding model.

        Raises:
            ValueError: If chunks list is empty
            RuntimeError: If embedding provider fails for all batches

        Example:
            >>> chunks = [
            ...     Chunk(id="1", text="First chunk", metadata={}),
            ...     Chunk(id="2", text="Second chunk", metadata={})
            ... ]
            >>> vectors = encoder.encode(chunks)
            >>> len(vectors) == len(chunks)  # True
        """
        if not chunks:
            raise ValueError("Cannot encode empty chunks list")

        # Extract text from chunks
        texts = [chunk.text for chunk in chunks]

        # Validate that all texts are non-empty
        for i, text in enumerate(texts):
            if not text or not text.strip():
                raise ValueError(
                    f"Chunk at index {i} (id={chunks[i].id}) has empty or whitespace-only text"
                )

        # Step 1: Hit the embedding cache for texts already encoded
        if self._cache is not None:
            cached_vectors, miss_indices = self._cache.get_many(texts)
        else:
            cached_vectors, miss_indices = [None] * len(texts), list(enumerate(texts))

        # If everything was a cache hit, return immediately
        if not miss_indices:
            return cached_vectors  # type: ignore[return-value]

        # Step 2: Extract miss texts and encode them in batches
        miss_texts = [texts[idx] for idx, _ in miss_indices]
        miss_vectors: list[list[float]] = []

        for batch_start in range(0, len(miss_texts), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(miss_texts))
            batch_texts = miss_texts[batch_start:batch_end]

            try:
                batch_vectors = self.embedding.embed(
                    texts=batch_texts,
                    trace=trace,
                )

                if len(batch_vectors) != len(batch_texts):
                    raise RuntimeError(
                        f"Embedding provider returned {len(batch_vectors)} vectors "
                        f"for {len(batch_texts)} texts in batch {batch_start}-{batch_end}"
                    )

                miss_vectors.extend(batch_vectors)

            except Exception as e:
                raise RuntimeError(
                    f"Failed to encode batch {batch_start}-{batch_end}: {str(e)}"
                ) from e

        # Step 3: Write miss results back to cache
        if self._cache is not None:
            self._cache.set_many(list(zip(miss_texts, miss_vectors)))

        # Step 4: Reassemble result in original order
        result: list[list[float]] = []
        miss_map = {idx: vec for idx, vec in zip([i for i, _ in miss_indices], miss_vectors)}
        for i in range(len(texts)):
            if cached_vectors[i] is not None:
                result.append(cached_vectors[i])  # type: ignore[arg-type]
            else:
                result.append(miss_map[i])

        # Final validation
        if len(result) != len(chunks):
            raise RuntimeError(
                f"Vector count mismatch: got {len(result)} vectors "
                f"for {len(chunks)} chunks"
            )

        if result:
            expected_dim = len(result[0])
            for i, vec in enumerate(result):
                if len(vec) != expected_dim:
                    raise RuntimeError(
                        f"Inconsistent vector dimensions: vector {i} has "
                        f"{len(vec)} dimensions, expected {expected_dim}"
                    )

        return result

    def get_batch_count(self, num_chunks: int) -> int:
        """Calculate number of batches needed for given chunk count.

        Utility method for logging/progress tracking.

        Args:
            num_chunks: Number of chunks to encode

        Returns:
            Number of batches required
        """
        if num_chunks <= 0:
            return 0
        return (num_chunks + self.batch_size - 1) // self.batch_size
