"""Debrief conversation agent — the SSE chat route (spec §3.1).

POST /api/v2/debrief/packets/{packet_id}/chat — org-walled, text/event-stream.
Body: DebriefChatRequest { message: 1..4000 }.

The route stays thin: auth, load the packet org-scoped (404 missing/cross-org,
409 when the body isn't ready yet), build the runner via the module-level
`_build_runner` factory (so tests can monkeypatch it), and stream the runner's
ChatEvents as `data: <json>\\n\\n` frames.

`_build_runner` binds the Cortex read seam: it reuses CortexGapReader's mockable
HTTP `_execute_query` + the in-process service-token minter, exposing a clean
`(cypher, params) -> rows` callable to DebriefReadTools. The graph read is
best-effort (read_tools collapses any failure to []), so token-mint / transport
errors never break the chat turn.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from typing import AsyncIterator
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.api.v2.schemas.debrief_chat import (
    DebriefActionRequest,
    DebriefChatRequest,
    DebriefConversationResponse,
    DebriefConversationTurn,
)
from app.api.v2.services import (
    feedback_service,
    pipeline_service,
)
from app.api.v2.services.candidate_decision_service import CandidateDecisionService
from app.api.v2.services.cortex_gap_reader import CortexGapReader, _parse_rows
from app.api.v2.services.cortex_insight_client import CortexInsightClient
from app.api.v2.services.debrief_repository import DebriefRepository
from app.config import get_settings
from app.dependencies import get_anthropic_async_client
from app.services.debrief_chat.action_service import DebriefActionService
from app.services.debrief_chat.contracts import ChatEvent, build_proposed_action
from app.services.debrief_chat.conversation_repository import (
    DebriefConversationRepository,
)
from app.services.debrief_chat.insight_service import DebriefInsightService
from app.services.debrief_chat.prompt import build_system_prompt
from app.services.debrief_chat.read_tools import DebriefReadTools
from app.services.debrief_chat.runner import DebriefChatRunner
from app.services.mcp.token_minter import mint_cortex_service_token

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/debrief", tags=["v2/debrief-chat"])


def _make_cortex_query(org_id: str):
    """A (cypher, params) -> rows callable over the org-bound Cortex MCP seam.

    Mints a per-org cortex:read token in-process (sync crypto -> to_thread), POSTs
    execute_query via CortexGapReader's mockable HTTP seam, and unwraps the rows.
    org_name is display-only on the JWT; Cortex force-binds group_id from org_id.
    """
    reader = CortexGapReader()

    async def cortex_query(cypher: str, params: dict) -> list[dict]:
        token, _ttl = await asyncio.to_thread(
            mint_cortex_service_token, org_id=org_id, org_name="OpenRecruiting"
        )
        resp = await reader._execute_query(token, cypher, params)
        return _parse_rows(resp)

    return cortex_query


def _build_runner(
    row: dict, current: CurrentUserWithOrg, supabase
) -> DebriefChatRunner:
    body = row["packet"]
    org_id = current.organization_id_str
    settings = get_settings()
    read_tools = DebriefReadTools(
        supabase=supabase,
        cortex_query=_make_cortex_query(org_id),
        packet=body,
        org_id=org_id,
        requisition_id=str(row.get("requisition_id") or "") or None,
    )
    return DebriefChatRunner(
        client=get_anthropic_async_client(),
        model=settings.DEBRIEF_CHAT_MODEL,
        max_iters=settings.DEBRIEF_CHAT_MAX_ITERS,
        max_tokens=settings.DEBRIEF_CHAT_MAX_TOKENS,
        packet_body=body,
        repo=DebriefConversationRepository(supabase),
        read_tools=read_tools,
        system_prompt=build_system_prompt(body),
        packet_id=str(row["id"]),
    )


def _make_cr_resolver(supabase, org_id: str, requisition_id: str):
    """A (candidate_id, round_ref) -> cr_id resolver over the pipeline read.

    Re-resolves the candidate_round id server-side (spec §4) — the LLM never
    supplies it. `round_ref` matches a round by its id OR its name. Returns "" when
    no match (the action service surfaces that as a ValidationError)."""

    async def resolve(candidate_id: str, round_ref: str | None) -> str:
        if not round_ref:
            return ""
        payload = await pipeline_service.get_role_candidates(
            supabase, org_id, UUID(str(requisition_id))
        )
        for candidate in payload.get("candidates") or []:
            if candidate.get("id") != candidate_id:
                continue
            for cr in candidate.get("candidate_rounds") or []:
                round_name = (cr.get("round") or {}).get("name")
                if round_ref in (cr.get("round_id"), round_name):
                    return cr.get("id") or ""
        return ""

    return resolve


def _build_action_service(
    row: dict, current: CurrentUserWithOrg, supabase
) -> DebriefActionService:
    body = row["packet"]
    org_id = current.organization_id_str
    requisition_id = row["requisition_id"]
    # The packet's authoritative id is the row id; the JSONB body may not carry
    # it. Seed it so the action service (e.g. log_insight) can reference packet_id.
    body.setdefault("id", row["id"])
    body.setdefault("requisition_id", requisition_id)
    return DebriefActionService(
        packet_body=body,
        org_id=org_id,
        supabase=supabase,
        feedback=feedback_service,
        pipeline=pipeline_service,
        decision=CandidateDecisionService(supabase),
        cr_resolver=_make_cr_resolver(supabase, org_id, requisition_id),
        insight=DebriefInsightService(supabase, CortexInsightClient()),
        created_by=str(current.user.id),
    )


async def _event_source(events: AsyncIterator[ChatEvent]) -> AsyncIterator[str]:
    async for event in events:
        yield f"data: {json.dumps(dataclasses.asdict(event))}\n\n"


@router.post("/packets/{packet_id}/chat")
async def debrief_chat(
    packet_id: UUID,
    body: DebriefChatRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> StreamingResponse:
    """Stream one recruiter→assistant turn over a generated packet."""
    row = await DebriefRepository(supabase).get_packet(
        str(packet_id), current.organization_id_str
    )
    if not row:
        raise NotFoundError("Debrief packet not found")
    if not row.get("packet"):
        raise ConflictError("PACKET_NOT_READY", "Debrief packet not ready")

    runner = _build_runner(row, current, supabase)
    return StreamingResponse(
        _event_source(runner.run(body.message)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/packets/{packet_id}/conversation")
async def debrief_conversation(
    packet_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> DebriefConversationResponse:
    """Return the persisted chat turns for a packet, oldest first.

    Org-walled exactly like /chat (404 missing/cross-org). A packet with no
    conversation yet returns an empty list — that's a legitimate state, not an
    error. Powers cross-device/post-reload history hydration in the FE."""
    row = await DebriefRepository(supabase).get_packet(
        str(packet_id), current.organization_id_str
    )
    if not row:
        raise NotFoundError("Debrief packet not found")

    turns = await DebriefConversationRepository(supabase).load_turns(str(packet_id))
    return DebriefConversationResponse(
        packet_id=str(packet_id),
        turns=[
            DebriefConversationTurn(
                role=str(turn.get("role") or ""),
                text=str(turn.get("text") or ""),
                idx=turn.get("idx"),
                ts=turn.get("ts"),
                proposed_action=turn.get("proposed_action"),
            )
            for turn in turns
            if isinstance(turn, dict)
        ],
    )


@router.post("/packets/{packet_id}/actions")
async def debrief_action(
    packet_id: UUID,
    body: DebriefActionRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    """Execute one confirmed action against a packet (spec §4).

    Thin: load the packet org-scoped (404 missing/cross-org), normalize the propose
    tool call into a ProposedAction, then delegate to DebriefActionService — which
    owns the packet-membership guard + the server-side cr_id re-resolution. Domain
    exceptions bubble to the global handlers (400 ValidationError, 404 NotFound,
    409 conflict); a malformed body is FastAPI's own 422."""
    row = await DebriefRepository(supabase).get_packet(
        str(packet_id), current.organization_id_str
    )
    if not row:
        raise NotFoundError("Debrief packet not found")
    if not row.get("packet"):
        raise ConflictError("PACKET_NOT_READY", "Debrief packet not ready")

    try:
        action = build_proposed_action(body.kind, body.input)
    except ValueError as exc:
        raise ValidationError("Invalid action") from exc

    service = _build_action_service(row, current, supabase)
    result = await service.execute(action)
    return {"ok": True, "result": result}
