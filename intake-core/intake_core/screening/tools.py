"""Tool-use schema + handler for the screening agent, in the OpenAI function shape.

Same shape as intake_core.tools.schemas, so voice-agent consumes
ALL_SCREENING_TOOLS exactly like ALL_TOOLS_OPENAI — through the same reader
(voice-agent/src/pipeline/tool_schemas.py). That shared reader is why the two
modules must change together: factory.build_pipeline reads config.tools
generically, and main.py hands it the intake tools for one pipeline and these for
the other, so flipping one module alone just moves the KeyError to the other
pipeline.
"""

from __future__ import annotations

MARK_QUESTION_COVERED = {
    "type": "function",
    "function": {
        "name": "mark_question_covered",
        "description": "Mark a screening question as sufficiently answered.",
        "parameters": {"type": "object", "properties": {
            "question_id": {"type": "string"}}, "required": ["question_id"]},
    },
}
ALL_SCREENING_TOOLS = [MARK_QUESTION_COVERED]


def handle_mark_question_covered(state: dict, question_id: str) -> dict:
    answered = set(state.get("answered", []))
    answered.add(question_id)
    state["answered"] = list(answered)
    return {"ok": True, "answered": state["answered"]}
