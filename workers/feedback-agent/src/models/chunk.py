from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

import numpy as np


@dataclass
class Utterance:
    text: str
    speaker: Optional[str] = None
    start_time: Optional[timedelta] = None
    end_time: Optional[timedelta] = None


@dataclass
class Chunk:
    id: str
    text: str
    token_count: int
    utterances: list[Utterance] = field(default_factory=list)
    start_time: Optional[timedelta] = None
    end_time: Optional[timedelta] = None
    summary: Optional[str] = None
    embedding: Optional[np.ndarray] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Chunk id cannot be empty")
