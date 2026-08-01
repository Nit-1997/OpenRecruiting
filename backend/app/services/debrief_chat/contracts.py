"""Wire contracts for the debrief chat agent.

`ChatEvent` — the SSE event the runner yields and the route serializes as
`data: <json>\\n\\n`.

`ProposedAction` / `ActionKind` — the uniform shape every `propose_*` tool emits
(spec §5). The runner intercepts a propose tool call (without executing it) and
the `/actions` endpoint consumes a ProposedAction to execute it after the human
confirm. `build_proposed_action` maps a propose tool name + args -> a validated
ProposedAction, packing the kind-specific fields into `params`.

This file owns all chat/action data contracts and stays pure (no I/O).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

ChatEventType = Literal["token", "proposed_action", "done", "error"]


@dataclass(slots=True)
class ChatEvent:
    """One streamed event in a debrief chat turn.

    type:
      - "token"           — an incremental assistant text chunk (data = str).
      - "proposed_action" — a write the agent proposes; terminal for the turn
                            (data = {"kind": str, "input": dict}). NOT executed.
      - "done"            — turn complete (data = {"turn_idx": int}).
      - "error"           — fail-soft; a STATIC message (data = {"message": str}).
    """

    type: ChatEventType
    data: Any = field(default=None)


class ActionKind(str, Enum):
    add_round = "add_round"
    # schedule_round was retired 2026-06-09: scheduling now opens the candidate's
    # pipeline packet UI (propose_open_scheduler, a FE-handled intent) — dates,
    # times, and timezones are picked there, never written through /actions.
    request_feedback = "request_feedback"
    record_decision = "record_decision"
    advance_reject = "advance_reject"
    # log_insight has a propose tool and dispatches to DebriefInsightService.
    log_insight = "log_insight"


class ProposedAction(BaseModel):
    """A write the agent proposes for human confirmation. NEVER executed by the
    LLM loop; the `/actions` endpoint executes it deterministically after confirm.
    """

    kind: ActionKind
    candidate_ids: list[str] = Field(default_factory=list)
    round_ref: str | None = None
    params: dict = Field(default_factory=dict)
    summary: str
    rationale: str


# Fields lifted out of the propose tool args onto the ProposedAction itself;
# everything else in the args becomes `params`.
_TOP_LEVEL_FIELDS = ("candidate_ids", "round_ref", "summary", "rationale")


def build_proposed_action(tool_name: str, args: dict) -> ProposedAction:
    """Map a `propose_<kind>` tool call -> a validated ProposedAction.

    Strips the `propose_` prefix to the ActionKind, lifts the uniform top-level
    fields out of `args`, and packs every remaining (kind-specific) field into
    `params`. An unknown or unproposable tool name raises ValueError.
    """
    prefix = "propose_"
    if not tool_name.startswith(prefix):
        raise ValueError(f"not a propose tool: {tool_name!r}")
    raw_kind = tool_name[len(prefix) :]
    if raw_kind not in _PROPOSABLE_KINDS:
        raise ValueError(f"unknown or unproposable action kind: {raw_kind!r}")

    params = {k: v for k, v in args.items() if k not in _TOP_LEVEL_FIELDS}
    return ProposedAction(
        kind=ActionKind(raw_kind),
        candidate_ids=args.get("candidate_ids") or [],
        round_ref=args.get("round_ref"),
        params=params,
        summary=args.get("summary"),
        rationale=args.get("rationale"),
    )


# The action kinds that have a propose tool. UI intents (propose_new_debrief,
# propose_open_scheduler) are deliberately absent — the FE acts on them directly
# and /actions must reject them.
_PROPOSABLE_KINDS = frozenset(
    {
        ActionKind.add_round.value,
        ActionKind.request_feedback.value,
        ActionKind.record_decision.value,
        ActionKind.advance_reject.value,
        ActionKind.log_insight.value,
    }
)
