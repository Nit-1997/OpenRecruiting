"""Anthropic tool-use schemas for update_answer + mark_status."""

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
