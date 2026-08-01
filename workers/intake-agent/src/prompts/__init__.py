"""v2 intake-agent prompts. v1's brief/classify/summarize stages are dropped because
intake_sessions.current_answers is already the structured equivalent.
"""

from .scorecard import (
    ROUNDS_JSON_SCHEMA,
    ROUND_DETAILS_JSON_SCHEMA,
    build_rounds_prompt,
    build_round_details_prompt,
)

__all__ = [
    "ROUNDS_JSON_SCHEMA",
    "ROUND_DETAILS_JSON_SCHEMA",
    "build_rounds_prompt",
    "build_round_details_prompt",
]
