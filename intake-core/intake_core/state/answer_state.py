"""Per-question answer state. Each question in a session has one AnswerState."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class AnswerStatus(str, Enum):
    UNTOUCHED = "untouched"
    NEEDS_PROBE = "needs_probe"
    DISCUSSED = "discussed"
    VALIDATED = "validated"
    SKIPPED = "skipped"


class Confidence(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class AnswerState:
    status: AnswerStatus = AnswerStatus.UNTOUCHED
    text: Optional[str] = None
    prefilled_text: Optional[str] = None
    extraction_confidence: Confidence = Confidence.NONE
    sources: list[str] = field(default_factory=list)
    turns_addressed: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["extraction_confidence"] = self.extraction_confidence.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AnswerState":
        return cls(
            status=AnswerStatus(d.get("status", "untouched")),
            text=d.get("text"),
            prefilled_text=d.get("prefilled_text"),
            extraction_confidence=Confidence(d.get("extraction_confidence", "none")),
            sources=list(d.get("sources", [])),
            turns_addressed=list(d.get("turns_addressed", [])),
        )


def new_untouched(
    prefilled_text: Optional[str] = None,
    confidence: Confidence = Confidence.NONE,
    sources: Optional[list[str]] = None,
) -> AnswerState:
    """Create a fresh AnswerState — initial text is the prefilled value (or None)."""
    return AnswerState(
        status=AnswerStatus.UNTOUCHED,
        text=prefilled_text,
        prefilled_text=prefilled_text,
        extraction_confidence=confidence,
        sources=list(sources or []),
        turns_addressed=[],
    )


def apply_user_input(
    s: AnswerState,
    text: str,
    confidence: Confidence,
    turn_idx: int,
) -> AnswerState:
    """Apply a new user-derived value. Advances status to DISCUSSED (agent/tracker can later mark VALIDATED)."""
    new_turns = list(s.turns_addressed)
    if turn_idx not in new_turns:
        new_turns.append(turn_idx)
    return AnswerState(
        status=AnswerStatus.DISCUSSED if s.status != AnswerStatus.VALIDATED else s.status,
        text=text,
        prefilled_text=s.prefilled_text,
        extraction_confidence=confidence,
        sources=list(s.sources),
        turns_addressed=new_turns,
    )
