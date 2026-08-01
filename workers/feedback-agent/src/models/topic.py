from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class Topic:
    id: str
    heading: str
    description: str
    embedding: Optional[np.ndarray] = field(default=None, repr=False)

    @property
    def full_text(self) -> str:
        return f"{self.heading}: {self.description}"


@dataclass
class TopicMatch:
    topic_id: str
    topic_heading: str
    similarity: float


@dataclass
class ChunkClassification:
    chunk_id: str
    matches: list[TopicMatch]
    is_off_topic: bool

    def __post_init__(self) -> None:
        self.matches = sorted(self.matches, key=lambda m: m.similarity, reverse=True)

    @property
    def primary_topic(self) -> Optional[TopicMatch]:
        return self.matches[0] if self.matches else None
