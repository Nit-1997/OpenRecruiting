from dataclasses import dataclass


@dataclass
class ChunkingConfig:
    target_chunk_size: int = 3500
    max_chunk_size: int = 4000
    min_chunk_size: int = 500
    overlap_ratio: float = 0.15
    percentile_threshold: float = 80.0
    buffer_size: int = 1
    preserve_speaker_turns: bool = True

    def __post_init__(self) -> None:
        if self.target_chunk_size <= self.min_chunk_size:
            raise ValueError(
                f"target_chunk_size ({self.target_chunk_size}) must be > "
                f"min_chunk_size ({self.min_chunk_size})"
            )
        if self.max_chunk_size < self.target_chunk_size:
            raise ValueError(
                f"max_chunk_size ({self.max_chunk_size}) must be >= "
                f"target_chunk_size ({self.target_chunk_size})"
            )
        if not 0.0 <= self.overlap_ratio <= 0.5:
            raise ValueError(
                f"overlap_ratio ({self.overlap_ratio}) must be between 0.0 and 0.5"
            )
        if not 0.0 <= self.percentile_threshold <= 100.0:
            raise ValueError(
                f"percentile_threshold ({self.percentile_threshold}) must be "
                f"between 0.0 and 100.0"
            )
        if self.buffer_size < 0:
            raise ValueError(f"buffer_size ({self.buffer_size}) must be >= 0")
