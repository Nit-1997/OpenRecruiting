"""Tool-use schemas for update_answer + mark_status, in the OpenAI function shape.

This is the only shape intake-core exports. It is what llm_core accepts
(llm_core/emulation.py rejects Anthropic `input_schema` outright rather than
translating it) and what voice-agent's pipeline reader consumes
(voice-agent/src/pipeline/tool_schemas.py).

The dual shape phase 3 shipped — an Anthropic `ALL_TOOLS` plus a derived
`ALL_TOOLS_OPENAI` sharing schema objects — is gone. It existed for exactly one
reason: voice-agent handed the Anthropic list straight to pipecat and no test
covered that path. That path is now read through a tested module, so the second
shape has no consumer, and carrying it would only be an invitation to send it
somewhere.
"""

from __future__ import annotations

from intake_core.questions import INTAKE_QUESTIONS

_QID_ENUM = [q["id"] for q in INTAKE_QUESTIONS]

UPDATE_ANSWER_TOOL = {
    "type": "function",
    "function": {
        "name": "update_answer",
        "description": (
            "Record what the recruiter just told you for one of the 9 intake questions. "
            "Call this after every user turn that contributes to a specific question. "
            "Pass the canonical question id (qid), the consolidated text (replace or append as appropriate), "
            "and a confidence reflecting how clear the user was. Optionally set status."
        ),
        "parameters": {
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
    },
}

MARK_STATUS_TOOL = {
    "type": "function",
    "function": {
        "name": "mark_status",
        "description": (
            "Update only the status of one question without changing its text. "
            "Use this when the recruiter explicitly skips a question ('skip that one'), "
            "or to mark a question validated after confirmation, without re-writing the text."
        ),
        "parameters": {
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
    },
}

ALL_TOOLS_OPENAI: list[dict] = [UPDATE_ANSWER_TOOL, MARK_STATUS_TOOL]
