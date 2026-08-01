"""DebriefActionService — validate + re-resolve + dispatch a confirmed action.

The single place the confirm-then-execute guardrail lives (spec §4):
  1. every `action.candidate_ids` MUST be a subset of the packet's candidates
     (checked BEFORE any dispatch);
  2. for round-scoped kinds, the `cr_id` is re-resolved server-side from
     `(candidate_id, round_ref)` via the injected `cr_resolver` — NEVER an
     LLM-supplied id;
  3. each kind dispatches in-process to the reused domain service.

Domain services are injected (the `pipeline` / `feedback` modules and a
`CandidateDecisionService`) so this stays unit-testable with mocks. The real domain
functions take `(supabase, org_id, ...)`, so `supabase` + the packet's
`requisition_id` are held here. `log_insight` dispatches to DebriefInsightService.
Scheduling has NO action kind: it is a FE-handled UI intent (propose_open_scheduler)
that opens the candidate's pipeline packet with the scheduling modal.
"""

from __future__ import annotations

from typing import Awaitable, Callable
from uuid import UUID

from app.api.v2.core.exceptions import ValidationError
from app.api.v2.schemas.candidate import AddCustomRoundRequest
from app.api.v2.schemas.feedback import RequestFeedbackRequest
from app.services.debrief_chat.contracts import ActionKind, ProposedAction

CrResolver = Callable[[str, str | None], Awaitable[str]]


def _require(params: dict, key: str):
    value = params.get(key)
    if value is None:
        raise ValidationError(f"missing required field: {key}")
    return value


class DebriefActionService:
    def __init__(
        self,
        *,
        packet_body: dict,
        org_id: str,
        supabase,
        feedback,
        pipeline,
        decision,
        cr_resolver: CrResolver,
        insight=None,
        created_by: str | None = None,
    ) -> None:
        self._packet = packet_body
        self._org_id = org_id
        self._db = supabase
        self._feedback = feedback
        self._pipeline = pipeline
        self._decision = decision
        self._cr_resolver = cr_resolver
        self._insight = insight
        self._created_by = created_by
        self._packet_candidate_ids = {
            c.get("candidate_id") for c in (packet_body.get("candidates") or [])
        }

    async def execute(self, action: ProposedAction) -> dict:
        self._guard_membership(action)
        handler = self._HANDLERS.get(action.kind)
        if handler is None:
            raise ValidationError(f"Unsupported action: {action.kind.value}")
        return await handler(self, action)

    # ------------------------------------------------------------------ #
    # Guardrail
    # ------------------------------------------------------------------ #
    def _guard_membership(self, action: ProposedAction) -> None:
        # Only log_insight may target zero candidates (an org/requisition-level
        # insight). Every other kind acts on a specific candidate. Either way, any
        # candidate id present MUST belong to this packet.
        if not action.candidate_ids and action.kind is not ActionKind.log_insight:
            raise ValidationError("Action targets no candidate")
        stray = [c for c in action.candidate_ids if c not in self._packet_candidate_ids]
        if stray:
            raise ValidationError("Action targets a candidate not in this debrief")

    def _single_candidate(self, action: ProposedAction) -> str:
        if len(action.candidate_ids) != 1:
            raise ValidationError(
                f"{action.kind.value} targets exactly one candidate"
            )
        return action.candidate_ids[0]

    async def _resolve_cr(self, candidate_id: str, round_ref: str | None) -> str:
        if not round_ref:
            raise ValidationError("round_ref is required for this action")
        cr_id = await self._cr_resolver(candidate_id, round_ref)
        if not cr_id:
            raise ValidationError("Could not resolve the round for this candidate")
        return cr_id

    # ------------------------------------------------------------------ #
    # Per-kind dispatch
    # ------------------------------------------------------------------ #
    async def _do_add_round(self, action: ProposedAction) -> dict:
        params = action.params
        body = AddCustomRoundRequest(
            name=_require(params, "name"),
            category=params.get("category"),
            duration_minutes=params.get("duration_minutes", 45),
            skills=params.get("skills"),
        )
        role_id = UUID(str(self._packet["requisition_id"]))
        for candidate_id in action.candidate_ids:
            await self._pipeline.add_custom_round(
                self._db, self._org_id, role_id, UUID(candidate_id), body
            )
        return {"ok": True, "result_summary": f"Added round '{body.name}'"}

    async def _do_request_feedback(self, action: ProposedAction) -> dict:
        candidate_id = self._single_candidate(action)
        cr_id = await self._resolve_cr(candidate_id, action.round_ref)
        params = action.params
        body = RequestFeedbackRequest(
            interviewer_email=_require(params, "interviewer_email"),
            interviewer_name=params.get("interviewer_name"),
            channel="email",
        )
        await self._feedback.request_feedback(
            self._db, self._org_id, UUID(str(cr_id)), body
        )
        return {"ok": True, "result_summary": "Requested interviewer feedback"}

    async def _do_record_decision(self, action: ProposedAction) -> dict:
        candidate_id = self._single_candidate(action)
        params = action.params
        verdict = _require(params, "verdict")
        await self._decision.set_verdict(
            candidate_id, verdict, params.get("status"), self._org_id
        )
        return {"ok": True, "result_summary": f"Recorded verdict '{verdict}'"}

    async def _do_advance_reject(self, action: ProposedAction) -> dict:
        candidate_id = self._single_candidate(action)
        cr_id = await self._resolve_cr(candidate_id, action.round_ref)
        outcome = _require(action.params, "outcome")
        await self._decision.set_round_outcome(str(cr_id), outcome, self._org_id)
        return {"ok": True, "result_summary": f"Recorded round outcome '{outcome}'"}

    async def _do_log_insight(self, action: ProposedAction) -> dict:
        if self._insight is None:
            raise ValidationError("log_insight is not available")
        params = action.params
        candidate_id = action.candidate_ids[0] if action.candidate_ids else None
        result = await self._insight.log(
            packet_id=self._packet["id"],
            requisition_id=self._packet["requisition_id"],
            organization_id=self._org_id,
            created_by=self._created_by,
            candidate_id=candidate_id,
            kind=_require(params, "insight_kind"),
            text=_require(params, "text"),
            triplet=params.get("triplet"),
        )
        return {"ok": True, "result_summary": "Logged insight", **result}

    _HANDLERS = {
        ActionKind.add_round: _do_add_round,
        ActionKind.request_feedback: _do_request_feedback,
        ActionKind.record_decision: _do_record_decision,
        ActionKind.advance_reject: _do_advance_reject,
        ActionKind.log_insight: _do_log_insight,
    }
