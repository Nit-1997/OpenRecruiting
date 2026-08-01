"""Request schemas for the debrief chat + actions endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class DebriefChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def _not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message cannot be empty or whitespace-only")
        return v


class DebriefConversationTurn(BaseModel):
    """One persisted chat turn, as stored on `debrief_conversations.turns`.

    `ts` is absent on turns persisted before server-side stamping shipped;
    `proposed_action` rides on assistant turns that ended in a propose_* call.
    """

    role: str
    text: str = ""
    idx: int | None = None
    ts: str | None = None
    proposed_action: dict | None = None


class DebriefConversationResponse(BaseModel):
    packet_id: str
    turns: list[DebriefConversationTurn]


class DebriefActionRequest(BaseModel):
    """Body for POST /debrief/packets/{id}/actions.

    Canonical contract: `kind` is the propose tool name (e.g. 'propose_add_round')
    and `input` is the tool's args. The route normalizes both into a ProposedAction
    via `build_proposed_action(kind, input)`.
    """

    kind: str = Field(..., min_length=1)
    input: dict = Field(default_factory=dict)
