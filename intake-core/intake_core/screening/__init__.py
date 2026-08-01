"""Screening agent core: question model, generic persona, dynamic prompt, tools.

Single source of the screening question model + per-turn prompt assembly,
consumed by both the voice agent and the backend.
"""

from intake_core.screening.builder import build_screening_prompt
from intake_core.screening.questions import ScreeningQuestion, snapshot_questions
from intake_core.screening.persona import (
    GENERIC_SCREENING_PERSONA,
    SCREENING_GUARDRAILS,
    PERSONA_DIMENSIONS,
)
from intake_core.screening.tools import (
    MARK_QUESTION_COVERED,
    ALL_SCREENING_TOOLS,
    handle_mark_question_covered,
)

__all__ = [
    "build_screening_prompt",
    "ScreeningQuestion",
    "snapshot_questions",
    "GENERIC_SCREENING_PERSONA",
    "SCREENING_GUARDRAILS",
    "PERSONA_DIMENSIONS",
    "MARK_QUESTION_COVERED",
    "ALL_SCREENING_TOOLS",
    "handle_mark_question_covered",
]
