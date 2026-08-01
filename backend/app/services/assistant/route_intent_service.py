"""Single responsibility: route a recruiter's free-text message to one live
product flow, or out-of-scope.

One Anthropic tool-use call. Any failure (or an unexpected value) returns
'out_of_scope' so the composer always offers the user a path forward (the two
routing chips).
"""
from __future__ import annotations

from typing import Any

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

_VALID = ("browse_roles", "intake_call", "debrief", "out_of_scope")

_TOOL = {
    "name": "emit_route",
    "description": (
        "Classify the recruiter's message into exactly one product flow. "
        "'browse_roles': they want to see, open, search, or review existing roles, "
        "requisitions, the roles board, or their pipeline of open positions. "
        "'intake_call': they want to create, draft, start, or kick off a NEW role "
        "(an intake). "
        "'debrief': they want to compare, debrief, or make a hire decision across "
        "MULTIPLE candidates / finalists on a role (a comparative decision packet). "
        "'out_of_scope': anything else — sourcing, analytics, general "
        "questions, greetings, or unclear requests."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": list(_VALID),
                "description": "The single best-matching flow. When unsure, 'out_of_scope'.",
            },
        },
        "required": ["intent"],
        "additionalProperties": False,
    },
}

_SYSTEM = (
    "You route a recruiter's free-text message to one of three live product flows, "
    "or mark it out of scope. Always call emit_route exactly once.\n\n"
    "- browse_roles: see / open / search / review existing roles, requisitions, the "
    "roles board, open positions, or pipeline. Examples: 'show me my open roles', "
    "'open the PM requisition', 'what roles do I have', 'go to roles'.\n"
    "- intake_call: create / draft / start / kick off a NEW role or req. Examples: "
    "'create a new role', 'I need to hire a backend engineer', 'start an intake for a "
    "designer', 'draft a requisition'.\n"
    "- debrief: compare / debrief / decide across MULTIPLE candidates or finalists on "
    "a role — a comparative hire-decision packet. Examples: 'debrief the PM finalists', "
    "'compare my top 3 backend candidates', 'help me decide who to hire for the "
    "designer role', 'run a debrief on the staff eng shortlist'.\n"
    "- out_of_scope: everything else — source candidates, analytics/insights, "
    "greetings, how-does-this-work, or anything unclear. When unsure, choose out_of_scope."
)


async def classify_route_intent(client: Any, text: str) -> str:
    """Return one of 'browse_roles' | 'intake_call' | 'debrief' | 'out_of_scope'."""
    try:
        msg = await client.messages.create(
            model=get_settings().ASSISTANT_INTENT_MODEL,
            max_tokens=64,
            system=_SYSTEM,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "emit_route"},
            messages=[{"role": "user", "content": text}],
        )
    except Exception as exc:  # noqa: BLE001 — never block the user on classification failure
        logger.warning("assistant_route_llm_failed", error=str(exc))
        return "out_of_scope"

    for block in getattr(msg, "content", []) or []:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == "emit_route"
        ):
            intent = (getattr(block, "input", {}) or {}).get("intent")
            return intent if intent in _VALID else "out_of_scope"
    return "out_of_scope"
