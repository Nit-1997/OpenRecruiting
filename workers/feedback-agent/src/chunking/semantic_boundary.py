from typing import Protocol
import numpy as np

from src.chunking.config import ChunkingConfig


class EmbeddingProvider(Protocol):
    """Protocol for embedding services."""

    def embed(self, texts: list[str]) -> np.ndarray: ...

    @property
    def dimension(self) -> int: ...


class SemanticBoundaryDetector:
    def __init__(
        self,
        embedding_service: EmbeddingProvider,
        config: ChunkingConfig | None = None,
    ):
        self._embedder = embedding_service
        self._config = config or ChunkingConfig()

    def detect_breakpoints(self, sentences: list[str]) -> list[int]:
        """
        Detect semantic breakpoints in a list of sentences.

        Returns list of indices where semantic breaks occur.
        Index i means break BEFORE sentence i (so sentence i starts new chunk).
        """
        if len(sentences) < 3:
            return []

        buffer = self._config.buffer_size

        groups = self._create_context_groups(sentences, buffer)

        embeddings = self._embedder.embed(groups)

        distances = self._compute_consecutive_distances(embeddings)

        if len(distances) == 0:
            return []

        breakpoints = self._find_breakpoints(distances)

        return breakpoints

    def _create_context_groups(
        self, sentences: list[str], buffer: int
    ) -> list[str]:
        """Create context-enriched groups for each sentence."""
        groups = []
        n = len(sentences)

        for i in range(n):
            start = max(0, i - buffer)
            end = min(n, i + buffer + 1)
            group_text = " ".join(sentences[start:end])
            groups.append(group_text)

        return groups

    def _compute_consecutive_distances(
        self, embeddings: np.ndarray
    ) -> np.ndarray:
        """Compute cosine distances between consecutive embeddings."""
        if len(embeddings) < 2:
            return np.array([])

        similarities = np.sum(embeddings[:-1] * embeddings[1:], axis=1)

        distances = 1.0 - similarities
        return distances

    def _find_breakpoints(self, distances: np.ndarray) -> list[int]:
        """Find breakpoint indices where distance exceeds threshold."""
        threshold = np.percentile(distances, self._config.percentile_threshold)

        breakpoints = [i + 1 for i, d in enumerate(distances) if d > threshold]

        return breakpoints

    def get_distances(self, sentences: list[str]) -> list[float]:
        """
        Get raw distance values for debugging/visualization.
        Returns list of distances between consecutive sentence groups.
        """
        if len(sentences) < 2:
            return []

        groups = self._create_context_groups(sentences, self._config.buffer_size)
        embeddings = self._embedder.embed(groups)
        distances = self._compute_consecutive_distances(embeddings)
        return distances.tolist()

    def refine_with_speaker_turns(
        self,
        breakpoints: list[int],
        speakers: list[str | None],
        min_chunk_size_sentences: int = 3,
    ) -> list[int]:
        """
        Refine breakpoints to prefer speaker turn boundaries.

        If a semantic breakpoint is within min_chunk_size_sentences of a
        speaker turn, shift it to the speaker turn boundary.

        Args:
            breakpoints: Raw semantic breakpoints
            speakers: Speaker for each sentence (parallel list)
            min_chunk_size_sentences: Minimum sentences before allowing break

        Returns:
            Refined breakpoint indices
        """
        if not breakpoints or len(speakers) < 2:
            return breakpoints

        speaker_turns = []
        for i in range(1, len(speakers)):
            if speakers[i] != speakers[i - 1]:
                speaker_turns.append(i)

        refined = []
        for bp in breakpoints:
            nearby_turn = self._find_nearby_speaker_turn(bp, speaker_turns, window=2)

            if nearby_turn is not None:
                refined.append(nearby_turn)
            else:
                refined.append(bp)

        refined = sorted(set(refined))

        if min_chunk_size_sentences > 0:
            refined = self._enforce_minimum_gap(refined, min_chunk_size_sentences)

        return refined

    def _find_nearby_speaker_turn(
        self, breakpoint: int, speaker_turns: list[int], window: int
    ) -> int | None:
        """Find speaker turn within window of breakpoint."""
        for turn in speaker_turns:
            if abs(turn - breakpoint) <= window:
                return turn
        return None

    def _enforce_minimum_gap(
        self, breakpoints: list[int], min_gap: int
    ) -> list[int]:
        """Remove breakpoints that are too close together."""
        if not breakpoints:
            return []

        result = [breakpoints[0]]
        for bp in breakpoints[1:]:
            if bp - result[-1] >= min_gap:
                result.append(bp)

        return result
