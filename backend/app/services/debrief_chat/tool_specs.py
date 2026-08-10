"""Tool definitions for the debrief chat agent, in OpenAI function shape.

READ_TOOL_SPECS — the in-loop, grounded read tools the model may call to fetch
evidence about candidates in this packet. Each is a templated, parameterized query
(the LLM never authors Cypher/SQL); `DebriefReadTools` validates every candidate_id
against the packet before any query runs.

PROPOSE_TOOL_SPECS — the propose_* action tools. Calling one does NOT execute the
action: the runner intercepts it, ends the turn with a single ProposedAction, and a
human confirms before the deterministic `/actions` endpoint runs it (spec §5). Each
description tells the model so. `propose_log_insight` is included — it proposes a
durable insight for Cortex.

This file owns all chat tool schemas (pure data).

OpenAI function shape ({"type": "function", "function": {"name", "description",
"parameters"}}) because llm_core speaks OpenAI to the LiteLLM gateway and REJECTS
Anthropic-shaped specs rather than translating them
(llm-core/llm_core/emulation.py:84-93). The schema bodies are unchanged from the
Anthropic revision; see the plan's Task 3 for the parse-both-revisions proof.
"""

from __future__ import annotations

# Shared across every propose tool — the uniform top-level fields of a
# ProposedAction. Kind-specific fields are merged in per tool below.
_PROPOSE_COMMON_PROPS: dict = {
    "candidate_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Ids of the candidate(s) in this packet this action targets.",
    },
    "summary": {
        "type": "string",
        "description": "A short human one-liner for the confirm-card title.",
    },
    "rationale": {
        "type": "string",
        "description": "Why you propose this, grounded in the packet — shown to the recruiter.",
    },
}
_PROPOSE_COMMON_REQUIRED = ["candidate_ids", "summary", "rationale"]

_ROUND_REF_PROP: dict = {
    "type": "string",
    "description": "The round this targets — its name (e.g. 'System Design') or its round id.",
}

READ_TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_candidate_detail",
            "description": (
                "Fetch one candidate's rounds with per-round rating, evaluation summary, "
                "outcome, and transcript availability. Use this to explain where a "
                "candidate's score came from or to compare rounds. The candidate must be "
                "one of the candidates in this debrief packet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "Id of a candidate in this packet.",
                    },
                },
                "required": ["candidate_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transcript_evidence",
            "description": (
                "Return short interview-transcript excerpts ({round_name, speaker, "
                "text}) for one candidate that mention a given topic or competency — "
                "the verbatim evidence behind a score. The topic is split into "
                "keywords and a segment matches when ANY keyword appears "
                "(case-insensitive), so 'system design tradeoffs' also finds segments "
                "that only say 'design'. If nothing matches, retry once with a single "
                "different keyword before telling the recruiter there's no evidence. "
                "The candidate must be one of the candidates in this debrief packet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "Id of a candidate in this packet.",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Topic or competency to find evidence for (e.g. 'system design').",
                    },
                    "round_ref": {
                        "type": "string",
                        "description": (
                            "Optional: restrict to one round by its exact name "
                            "(e.g. 'System Design') or round id."
                        ),
                    },
                },
                "required": ["candidate_id", "topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_graph_standing",
            "description": (
                "Best-effort cross-candidate competency standing from the org's "
                "knowledge graph (how candidates compare on a competency). Returns an "
                "empty result when the graph has no relevant signal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "Optional: restrict to one candidate in this packet.",
                    },
                    "competency": {
                        "type": "string",
                        "description": "Optional: a competency name to compare standing on.",
                    },
                },
                "required": [],
            },
        },
    },
]


_PROPOSE_NOT_EXECUTED = (
    "This PROPOSES an action for the recruiter to confirm — it is NOT executed. "
)


PROPOSE_TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "propose_add_round",
            "description": (
                _PROPOSE_NOT_EXECUTED
                + "Propose adding a new per-candidate interview round (e.g. a deeper "
                "system-design round) when the packet shows a gap worth closing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_PROPOSE_COMMON_PROPS,
                    "name": {
                        "type": "string",
                        "description": "Name of the new round (e.g. 'System Design Deep Dive').",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional round category (e.g. 'technical', 'behavioral').",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Optional round length in minutes.",
                    },
                    "skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional skills the round should probe.",
                    },
                },
                "required": [*_PROPOSE_COMMON_REQUIRED, "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_open_scheduler",
            "description": (
                "Open candidates' pipeline packets in the app with the scheduling "
                "UI — the recruiter picks the date, time, and timezone THERE, never "
                "in chat. Call this whenever the recruiter wants to schedule, "
                "reschedule, or book any round for candidates in this debrief — "
                "even if they typed a date/time in chat, the picker is where it is "
                "confirmed. Do not ask for dates, times, or timezones in chat. Pass "
                "ALL candidates being scheduled (the app walks the recruiter through "
                "them one by one); pass round_ref when a specific round was named."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "EVERY candidate being scheduled, in the order to work "
                            "through them — not just the first."
                        ),
                    },
                    "round_ref": _ROUND_REF_PROP,
                },
                "required": ["candidate_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_request_feedback",
            "description": (
                _PROPOSE_NOT_EXECUTED
                + "Propose emailing an interviewer a request to capture feedback for a "
                "candidate's round that is missing it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_PROPOSE_COMMON_PROPS,
                    "round_ref": _ROUND_REF_PROP,
                    "interviewer_email": {
                        "type": "string",
                        "description": "Email of the interviewer to request feedback from.",
                    },
                    "interviewer_name": {
                        "type": "string",
                        "description": "Optional interviewer display name.",
                    },
                },
                "required": [*_PROPOSE_COMMON_REQUIRED, "interviewer_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_record_decision",
            "description": (
                _PROPOSE_NOT_EXECUTED
                + "Propose recording the hiring decision (final verdict) for a candidate, "
                "optionally also updating their pipeline status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_PROPOSE_COMMON_PROPS,
                    "verdict": {
                        "type": "string",
                        "enum": ["strong_hire", "hire", "no_hire", "strong_no_hire"],
                        "description": "The hiring verdict for the candidate.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "hired", "rejected", "withdrawn"],
                        "description": "Optional pipeline status to set alongside the verdict.",
                    },
                },
                "required": [*_PROPOSE_COMMON_REQUIRED, "verdict"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_advance_reject",
            "description": (
                _PROPOSE_NOT_EXECUTED
                + "Propose the outcome of a candidate's round — advance, reject, or hold."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_PROPOSE_COMMON_PROPS,
                    "round_ref": _ROUND_REF_PROP,
                    "outcome": {
                        "type": "string",
                        "enum": ["advance", "reject", "hold"],
                        "description": "The outcome to record for the round.",
                    },
                },
                "required": [*_PROPOSE_COMMON_REQUIRED, "outcome"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_new_debrief",
            "description": (
                "Restart the debrief WORKFLOW in the app — the recruiter is handed "
                "back to the picker UI; nothing is written to any data. Call this "
                "whenever the recruiter wants a NEW comparison: debrief another "
                "role, debrief 'another round', compare a different set of "
                "candidates, or start over. Do NOT use propose_add_round for that "
                "intent, and do NOT ask clarifying questions first — the picker "
                "collects the choices. scope='same_role' reopens the candidate "
                "picker for this packet's role; scope='different_role' opens the "
                "role picker."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["same_role", "different_role"],
                        "description": (
                            "same_role = a new candidate set on this packet's role; "
                            "different_role = pick a different role first."
                        ),
                    },
                },
                "required": ["scope"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_quick_replies",
            "description": (
                "Attach tappable quick-reply pills to your reply — the recruiter "
                "taps one and it is sent as their next message. Use this INSTEAD of "
                "enumerating options in prose: when asked what you can do, when an "
                "ask is ambiguous between several actions or candidates, or when "
                "you would otherwise end with a multi-option question. Write ONE "
                "short sentence first, then call this with 3-6 options. Each option "
                "must be a short, complete, actionable ask (e.g. 'Pull Zara's "
                "round-by-round detail', 'Log this learning to Cortex')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3-6 short tappable replies, most useful first.",
                    },
                },
                "required": ["options"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_log_insight",
            "description": (
                "PROPOSE logging a durable insight to Cortex for the recruiter to "
                "confirm — not executed until confirmed. Use this when the conversation "
                "surfaces a lasting signal worth compounding in the org's intelligence: "
                "a decision rationale (why a candidate won) or a recruiter preference "
                "(what this team weights). candidate_ids may be empty for an "
                "org/requisition-level insight."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional ids of the candidate(s) this insight is about; "
                            "leave empty for an org/requisition-level insight."
                        ),
                    },
                    "summary": _PROPOSE_COMMON_PROPS["summary"],
                    "rationale": _PROPOSE_COMMON_PROPS["rationale"],
                    "insight_kind": {
                        "type": "string",
                        "enum": ["decision_rationale", "recruiter_preference"],
                        "description": (
                            "decision_rationale = narrative why; recruiter_preference = "
                            "a durable weighting/trait this team values."
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": "The insight itself, in the recruiter's words.",
                    },
                    "triplet": {
                        "type": "object",
                        "description": (
                            "Optional structured fact for a recruiter_preference "
                            "(subject/predicate/object)."
                        ),
                        "properties": {
                            "subject": {"type": "string"},
                            "predicate": {"type": "string"},
                            "object": {"type": "string"},
                        },
                    },
                },
                "required": ["summary", "rationale", "insight_kind", "text"],
            },
        },
    },
]
