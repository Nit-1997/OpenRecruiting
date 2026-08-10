"""Tool-use schemas for update_answer + mark_status, in both wire shapes.

ALL_TOOLS is Anthropic-shaped and still feeds the voice agent (phase 7).
ALL_TOOLS_OPENAI is derived from it and feeds the backend text runner through the
LiteLLM gateway. See _as_openai_tool for why the derivation shares objects.
"""

from __future__ import annotations

from intake_core.questions import INTAKE_QUESTIONS

_QID_ENUM = [q["id"] for q in INTAKE_QUESTIONS]

UPDATE_ANSWER_TOOL = {
    "name": "update_answer",
    "description": (
        "Record what the recruiter just told you for one of the 9 intake questions. "
        "Call this after every user turn that contributes to a specific question. "
        "Pass the canonical question id (qid), the consolidated text (replace or append as appropriate), "
        "and a confidence reflecting how clear the user was. Optionally set status."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "qid": {
                "type": "string",
                "enum": _QID_ENUM,
                "description": "Canonical question id (e.g. 'q4_must_haves').",
            },
            "text": {
                "type": "string",
                "description": "The consolidated answer text after this turn.",
            },
            "confidence": {
                "type": "string",
                "enum": ["none", "low", "medium", "high"],
                "description": "How clearly the recruiter expressed this. 'high' = explicit + specific.",
            },
            "status": {
                "type": "string",
                "enum": ["untouched", "needs_probe", "discussed", "validated", "skipped"],
                "description": "Optional. Default 'discussed'. Use 'validated' when the recruiter has firmly confirmed.",
            },
        },
        "required": ["qid", "text", "confidence"],
    },
}

MARK_STATUS_TOOL = {
    "name": "mark_status",
    "description": (
        "Update only the status of one question without changing its text. "
        "Use this when the recruiter explicitly skips a question ('skip that one'), "
        "or to mark a question validated after confirmation, without re-writing the text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "qid": {
                "type": "string",
                "enum": _QID_ENUM,
            },
            "status": {
                "type": "string",
                "enum": ["untouched", "needs_probe", "discussed", "validated", "skipped"],
            },
        },
        "required": ["qid", "status"],
    },
}

ALL_TOOLS: list[dict] = [UPDATE_ANSWER_TOOL, MARK_STATUS_TOOL]


def _as_openai_tool(tool: dict) -> dict:
    """Render an Anthropic-shaped spec in the OpenAI function shape.

    `parameters` is the SAME OBJECT as `input_schema`, not a copy. That is
    deliberate: it makes "the schema was moved, not retyped" true by
    construction and assertable with `is`, which a diff cannot show because
    reindentation touches every line. Both lists are read-only module data and
    nothing in this repo mutates a tool schema.
    """
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


# TEMPORARY DUAL SHAPE, and it has an owner.
#
# ALL_TOOLS stays Anthropic-shaped because voice-agent/src/main.py:43 still hands
# it to pipecat's AnthropicLLMService — phase 7's surface, with no test covering
# it. ALL_TOOLS_OPENAI is what the backend text runner sends to the LiteLLM
# gateway from phase 3 onward; llm_core rejects `input_schema` outright rather
# than translating it.
#
# Phase 4 makes the OpenAI form canonical and deletes _as_openai_tool together
# with the Anthropic one, at the same moment phase 7 stops needing it.
ALL_TOOLS_OPENAI: list[dict] = [_as_openai_tool(tool) for tool in ALL_TOOLS]
