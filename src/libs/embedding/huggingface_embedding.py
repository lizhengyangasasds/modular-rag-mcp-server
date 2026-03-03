"""HuggingFace Embedding implementation for local embedding models.

This module provides the HuggingFace Embedding implementation that works with
sentence-transformers models like all-MiniLM-L6-v2, deployed locally.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from src.libs.embedding.base_embedding import BaseEmbedding


class HuggingFaceEmbeddingError(RuntimeError):
    """Raised when HuggingFace Embeddings fails."""


class HuggingFaceEmbedding(BaseEmbedding):
    """HuggingFace Embedding provider implementation using sentence-transformers.
    
    This class implements the BaseEmbedding interface for local embedding generation
    using HuggingFace sentence-transformers models.
    
    Attributes:
        model_name: The model identifier (e.g., 'all-MiniLM-L6-v2').
        dimension: The dimensionality of embeddings produced by this model.
        device: The device to run the model on ('cpu' or 'cuda').
    
    Example:
        >>> from src.core.settings import load_settings
        >>> settings = load_settings('config/settings.yaml')
        >>> embedding = HuggingFaceEmbedding(settings)
        >>> vectors = embedding.embed(["hello world", "test"])
    """
    
    DEFAULT_DIMENSION = 384  # all-MiniLM-L6-v2 produces 384-dim embeddings
    DEFAULT_DEVICE = "cpu"
    _MODEL_CACHE: Dict[str, Any] = {}
    _MODEL_LOCK = threading.Lock()

    def __init__(
        self,
        settings: Any,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the HuggingFace Embedding provider.
        
        Args:
            settings: Application settings containing Embedding configuration.
            model_name: Optional model name override.
            device: Optional device override ('cpu' or 'cuda').
            **kwargs: Additional configuration overrides.
        
        Raises:
            ValueError: If required configuration is missing.
        """
        self.model_name = model_name or settings.embedding.model
        self.device = device or getattr(settings.embedding, 'device', self.DEFAULT_DEVICE)
        self.dimension = getattr(settings.embedding, 'dimensions', self.DEFAULT_DIMENSION)
        self._model = None
        self._extra_config = kwargs

    @property
    def model(self) -> Any:
        """Lazy load the model (thread-safe singleton pattern)."""
        if self._model is None:
            with self._MODEL_LOCK:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                    except ImportError as e:
                        raise HuggingFaceEmbeddingError(
                            "sentence-transformers library is required for HuggingFace Embedding. "
                            "Install with: pip install sentence-transformers"
                        ) from e
                    
                    cache_key = f"{self.model_name}:{self.device}"
                    if cache_key not in HuggingFaceEmbedding._MODEL_CACHE:
                        HuggingFaceEmbedding._MODEL_CACHE[cache_key] = SentenceTransformer(
                            self.model_name,
                            device=self.device
                        )
                    self._model = HuggingFaceEmbedding._MODEL_CACHE[cache_key]
        return self._model

    def embed(
        self,
        texts: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[List[float]]:
        """Generate embeddings for a batch of texts using HuggingFace sentence-transformers.
        
        Args:
            texts: List of text strings to embed. Must not be empty.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Additional parameters (currently unused, reserved for future).
        
        Returns:
            List of embedding vectors, where each vector is a list of floats.
        
        Raises:
            ValueError: If texts list is empty or contains invalid entries.
            HuggingFaceEmbeddingError: If model inference fails.
        """
        self.validate_texts(texts)
        
        try:
            embeddings = self.model.encode(
                texts,
                convert_to_numpy=True,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            
            # Convert numpy arrays to lists
            return [emb.tolist() for emb in embeddings]
            
        except Exception as e:
            raise HuggingFaceEmbeddingError(
                f"Failed to generate embeddings: {str(e)}"
            ) from e

    def get_dimension(self) -> int:
        """Get the dimensionality of embeddings produced by this provider.
        
        Returns:
            The vector dimension configured for this instance.
        
        Note:
            Common dimensions:
            - all-MiniLM-L6-v2: 384
            - all-mpnet-base-v2: 768
        """
        return self.dimension
