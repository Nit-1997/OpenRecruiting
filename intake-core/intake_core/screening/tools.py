"""Anthropic tool-use schema + handler for the screening agent.

Schema shape (plain dict with 'input_schema') matches intake_core.tools.schemas
so the voice agent can consume ALL_SCREENING_TOOLS exactly like ALL_TOOLS.
"""

from __future__ import annotations

MARK_QUESTION_COVERED = {
    "name": "mark_question_covered",
    "description": "Mark a screening question as sufficiently answered.",
    "input_schema": {"type": "object", "properties": {
        "question_id": {"type": "string"}}, "required": ["question_id"]},
}
ALL_SCREENING_TOOLS = [MARK_QUESTION_COVERED]


def handle_mark_question_covered(state: dict, question_id: str) -> dict:
    answered = set(state.get("answered", []))
    answered.add(question_id)
    state["answered"] = list(answered)
    return {"ok": True, "answered": state["answered"]}
