from sentence_transformers import SentenceTransformer
import numpy as np
from typing import Optional


class EmbeddingService:
    """Singleton embedding service with lazy model loading."""

    _instance: Optional['EmbeddingService'] = None

    def __new__(cls, model_name: str = "BAAI/bge-small-en-v1.5"):
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._model_name = model_name
            instance._model: Optional[SentenceTransformer] = None
            cls._instance = instance
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing."""
        cls._instance = None

    def _ensure_model(self) -> SentenceTransformer:
        """Lazy load the embedding model."""
        if self._model is None:
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        Generate normalized embeddings for texts.

        Args:
            texts: List of strings to embed

        Returns:
            numpy array of shape (len(texts), dimension)
        """
        if not texts:
            return np.array([]).reshape(0, self.dimension)

        model = self._ensure_model()
        return model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 100,
            batch_size=32
        )

    def embed_single(self, text: str) -> np.ndarray:
        """Embed a single text, returns 1D array."""
        return self.embed([text])[0]

    @property
    def dimension(self) -> int:
        """Embedding dimension (384 for bge-small-en-v1.5)."""
        return 384

    @property
    def max_seq_length(self) -> int:
        """Maximum sequence length in tokens (512 for bge-small-en-v1.5)."""
        return 512

    @property
    def model_name(self) -> str:
        """Name of the embedding model."""
        return self._model_name
