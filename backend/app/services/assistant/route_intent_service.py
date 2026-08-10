"""Single responsibility: route a recruiter's free-text message to one live
product flow, or out-of-scope.

One gateway tool-use call. Any failure (or an unexpected value) returns
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
    "type": "function",
    "function": {
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
        "parameters": {
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
    },
}

_FORCE_TOOL = {"type": "function", "function": {"name": "emit_route"}}

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


async def classify_route_intent(llm: Any, text: str) -> str:
    """Return one of 'browse_roles' | 'intake_call' | 'debrief' | 'out_of_scope'.

    The tool is forced. This site has the tightest budget of the nine — 64 tokens,
    enough for the tool call and nothing else — so the prose preamble measured at
    8.75% on the JD guardrail would not merely waste tokens here, it would leave
    no room for the call at all. Everything below degrades to 'out_of_scope',
    which is silently wrong rather than visibly broken: the recruiter gets the
    two routing chips instead of the flow they asked for.
    """
    try:
        reply = await llm.complete(
            model=get_settings().ASSISTANT_INTENT_MODEL,
            max_tokens=64,
            system=_SYSTEM,
            tools=[_TOOL],
            tool_choice=_FORCE_TOOL,
            messages=[{"role": "user", "content": text}],
        )
    except Exception as exc:  # noqa: BLE001 — never block the user on classification failure
        logger.warning("assistant_route_llm_failed", error=str(exc))
        return "out_of_scope"

    # tool_call_named returns None for a prose reply AND for a reply naming some
    # other tool — both of which the block loop treated as out_of_scope too.
    call = reply.tool_call_named("emit_route")
    if call is None:
        return "out_of_scope"
    intent = call.arguments.get("intent")
    return intent if intent in _VALID else "out_of_scope"
