"""Single responsibility: extract structured role fields from free-text intent.

One gateway tool-use call. Extracts only fields present in the text; absent
fields are None. Any failure returns all-None so the UI never blocks the user
from starting an intake.
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_EMPTY = {"role_name": None, "exp_min": None, "exp_max": None, "location": None, "intent": "other", "list_status": None}

_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_role_fields",
        "description": (
            "Classify the recruiter's message and emit any structured fields. "
            "Always set intent to one of: 'create_role', 'list_sessions', or 'other'. "
            "For 'create_role': extract role_name, exp_min, exp_max, location from the message. "
            "For 'list_sessions': set list_status to the requested filter. "
            "Treat any of these as a role-creation request: 'req', 'requisition', 'role', "
            "'position', 'opening', 'hire', 'hiring for', 'need a', 'looking for'. "
            "Treat any of these as a list request: 'show', 'list', 'see', 'what', 'display', "
            "'get me', followed by words like 'intakes', 'roles', 'sessions', 'reqs'. "
            "Extract the job TITLE as role_name (title-cased), e.g. 'Product Manager', "
            "'Senior Backend Engineer', 'iOS Developer'. "
            "Extract city, region, or work arrangement as location, e.g. 'San Francisco', "
            "'Remote · US', 'New York', 'Remote'. "
            "Extract experience ranges as exp_min/exp_max when present (e.g. '5-9 yrs' → 5/9, "
            "'3+ years' → exp_min=3). "
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["create_role", "list_sessions", "other"],
                    "description": (
                        "Classify the message: 'create_role' if creating/drafting/starting a role, "
                        "'list_sessions' if viewing/listing/showing existing intakes or roles, "
                        "'other' otherwise."
                    ),
                },
                "list_status": {
                    "type": "string",
                    "enum": ["pending", "published", "submitted", "active", "all"],
                    "description": (
                        "Only set when intent='list_sessions'. Filter: 'pending' = not-yet-completed intakes, "
                        "'published' = published roles, 'submitted' = submitted, 'active' = active, "
                        "'all' if unspecified or user wants everything. Omit if intent != 'list_sessions'."
                    ),
                },
                "role_name": {
                    "type": "string",
                    "description": (
                        "Job title, title-cased. Examples: 'Product Manager', "
                        "'Senior Backend Engineer', 'Data Scientist'. Omit if absent."
                    ),
                },
                "exp_min": {"type": "integer", "description": "Minimum years experience. Omit if absent."},
                "exp_max": {"type": "integer", "description": "Maximum years experience. Omit if absent."},
                "location": {
                    "type": "string",
                    "description": (
                        "City, region, or arrangement. Examples: 'San Francisco', "
                        "'Remote · US', 'New York', 'Remote'. Omit if absent."
                    ),
                },
            },
            "additionalProperties": False,
        },
    },
}

_SYSTEM = (
    "You classify a recruiter's free-text message and extract structured fields. "
    "Always call emit_role_fields and always set intent.\n\n"
    "INTENT CLASSIFICATION:\n"
    "- 'create_role': user wants to create/draft/start/open a new role, req, or requisition. "
    "Signals: 'req', 'requisition', 'opening', 'position', 'role', 'need a <title>', "
    "'hire a <title>', 'looking for a <title>', 'create', 'draft', 'start a new'. "
    "Extract role_name (title-cased), exp_min, exp_max, location when present.\n"
    "- 'list_sessions': user wants to SEE/list/show/view existing intakes, roles, or sessions. "
    "Signals: 'show', 'list', 'see', 'display', 'get me', 'what are my', 'view' + "
    "'intakes'/'roles'/'sessions'/'reqs'. Set list_status to: 'pending' if they say pending/"
    "waiting/incomplete, 'published' if published, 'submitted' if submitted, 'active' if active, "
    "'all' if unspecified or they want all. Do NOT extract role fields for list queries.\n"
    "- 'other': greeting, question about how it works, anything else.\n\n"
    "Examples:\n"
    "  'create a new req in San Francisco for a Product Manager role' "
    "→ intent='create_role', role_name='Product Manager', location='San Francisco'\n"
    "  'I need a Senior Backend Engineer, 5-9 yrs, remote US' "
    "→ intent='create_role', role_name='Senior Backend Engineer', exp_min=5, exp_max=9, location='Remote · US'\n"
    "  'show me pending intakes' → intent='list_sessions', list_status='pending'\n"
    "  'list all my roles' → intent='list_sessions', list_status='all'\n"
    "  'what roles are waiting on intake?' → intent='list_sessions', list_status='pending'\n"
    "  'show published roles' → intent='list_sessions', list_status='published'\n"
    "  'how does this work?' → intent='other'"
)

# A GATEWAY ALIAS, not a provider model id (litellm-config.yaml maps it to haiku).
# This is the one call site in the backend whose model is not read from settings;
# it was hardcoded before the migration and stays hardcoded after it.
_MODEL = "parse-role-intent"

_FORCE_TOOL = {"type": "function", "function": {"name": "emit_role_fields"}}


async def parse_role_intent(llm: Any, text: str) -> dict[str, Any]:
    """Return {role_name, exp_min, exp_max, location} with None for anything not found."""
    try:
        reply = await llm.complete(
            model=_MODEL,
            max_tokens=400,
            system=_SYSTEM,
            tools=[_TOOL],
            tool_choice=_FORCE_TOOL,
            messages=[{"role": "user", "content": text}],
        )
    except Exception as exc:  # noqa: BLE001 — never block the user on extraction failure
        logger.warning("parse_intent_llm_failed", error=str(exc))
        return dict(_EMPTY)

    # The forcing survived the migration in OpenAI shape rather than being
    # dropped in favour of _SYSTEM's "Always call emit_role_fields". A prose reply
    # still lands on the all-None result the empty-content case produced before,
    # so this branch stays as defence in depth.
    call = reply.tool_call_named("emit_role_fields")
    args: dict[str, Any] = call.arguments if call else {}

    raw_intent = args.get("intent") or "other"
    intent = raw_intent if raw_intent in ("create_role", "list_sessions", "other") else "other"
    raw_status = args.get("list_status") or None
    list_status = (
        raw_status
        if raw_status in ("pending", "published", "submitted", "active", "all")
        else None
    )
    return {
        "role_name": args.get("role_name") or None,
        "exp_min": args.get("exp_min"),
        "exp_max": args.get("exp_max"),
        "location": args.get("location") or None,
        "intent": intent,
        "list_status": list_status,
    }
