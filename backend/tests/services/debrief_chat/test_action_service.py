"""Tests for DebriefActionService — validate + re-resolve + dispatch (spec §4).

The guardrail (candidate(s) subset of the packet) lives here and runs BEFORE any
dispatch. cr_id is re-resolved server-side from (candidate_id, round_ref) via an
injected resolver — never an LLM-supplied id. Domain services (feedback /
pipeline / decision) are mocked modules; we assert each kind dispatches with the
mapped params and the resolved cr_id.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v2.core.exceptions import ValidationError
from app.services.debrief_chat.action_service import DebriefActionService
from app.services.debrief_chat.contracts import ActionKind, ProposedAction

ORG_ID = "00000000-0000-0000-0000-000000000010"
REQ_ID = "00000000-0000-0000-0000-0000000000b1"
CAND_A = "00000000-0000-0000-0000-0000000000a1"
CAND_B = "00000000-0000-0000-0000-0000000000a2"
RESOLVED_CR = "00000000-0000-0000-0000-0000000000c9"


def _packet():
    return {
        "requisition_id": REQ_ID,
        "role_title": "PM",
        "candidates": [
            {"candidate_id": CAND_A, "name": "Ada"},
            {"candidate_id": CAND_B, "name": "Bob"},
        ],
    }


USER_ID = "00000000-0000-0000-0000-000000000001"


def _packet_with_id():
    base = _packet()
    base["id"] = "00000000-0000-0000-0000-0000000000f1"
    return base


def _service(*, cr_resolver=None, insight=None, **overrides):
    feedback = MagicMock()
    feedback.request_feedback = AsyncMock(return_value={"sent": True})
    pipeline = MagicMock()
    pipeline.add_custom_round = AsyncMock(return_value={"round": {}})
    decision = MagicMock()
    decision.set_verdict = AsyncMock(return_value={"final_verdict": "hire"})
    decision.set_round_outcome = AsyncMock(return_value={"outcome": "advance"})

    if cr_resolver is None:
        cr_resolver = AsyncMock(return_value=RESOLVED_CR)

    svc = DebriefActionService(
        packet_body=_packet_with_id(),
        org_id=ORG_ID,
        supabase=MagicMock(),
        feedback=overrides.get("feedback", feedback),
        pipeline=overrides.get("pipeline", pipeline),
        decision=overrides.get("decision", decision),
        cr_resolver=cr_resolver,
        insight=insight,
        created_by=USER_ID,
    )
    return svc, feedback, pipeline, decision, cr_resolver


# ---------------------------------------------------------------------------
# Membership guard (runs before any dispatch)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_candidate_not_in_packet_raises_before_dispatch():
    svc, _, pipeline, decision, _ = _service()
    action = ProposedAction(
        kind=ActionKind.record_decision,
        candidate_ids=["00000000-0000-0000-0000-0000000000ff"],
        params={"verdict": "hire"},
        summary="s",
        rationale="r",
    )
    with pytest.raises(ValidationError):
        await svc.execute(action)
    decision.set_verdict.assert_not_awaited()
    pipeline.add_custom_round.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_candidate_ids_raises():
    svc, *_ = _service()
    action = ProposedAction(
        kind=ActionKind.record_decision,
        candidate_ids=[],
        params={"verdict": "hire"},
        summary="s",
        rationale="r",
    )
    with pytest.raises(ValidationError):
        await svc.execute(action)


# ---------------------------------------------------------------------------
# add_round -> pipeline.add_custom_round per candidate
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_add_round_dispatches_to_pipeline():
    svc, _, pipeline, _, _ = _service()
    action = ProposedAction(
        kind=ActionKind.add_round,
        candidate_ids=[CAND_A],
        params={
            "name": "System Design",
            "category": "technical",
            "duration_minutes": 60,
            "skills": ["architecture"],
        },
        summary="s",
        rationale="r",
    )
    out = await svc.execute(action)
    assert out["ok"] is True
    pipeline.add_custom_round.assert_awaited_once()
    kwargs = pipeline.add_custom_round.await_args
    # positional: (supabase, org_id, role_id, candidate_id, body)
    args = kwargs.args
    assert args[1] == ORG_ID
    assert str(args[2]) == REQ_ID
    assert str(args[3]) == CAND_A
    body = args[4]
    assert body.name == "System Design"
    assert body.category == "technical"
    assert body.duration_minutes == 60
    assert body.skills == ["architecture"]


# ---------------------------------------------------------------------------
# request_feedback -> cr_resolver then feedback.request_feedback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_request_feedback_resolves_cr_and_dispatches():
    svc, feedback, _, _, cr_resolver = _service()
    action = ProposedAction(
        kind=ActionKind.request_feedback,
        candidate_ids=[CAND_A],
        round_ref="abc-round",
        params={"interviewer_email": "bob@x.com", "interviewer_name": "Bob"},
        summary="s",
        rationale="r",
    )
    await svc.execute(action)
    cr_resolver.assert_awaited_once_with(CAND_A, "abc-round")
    feedback.request_feedback.assert_awaited_once()
    args = feedback.request_feedback.await_args.args
    assert args[1] == ORG_ID
    assert str(args[2]) == RESOLVED_CR
    body = args[3]
    assert str(body.interviewer_email) == "bob@x.com"
    assert body.channel == "email"


# ---------------------------------------------------------------------------
# record_decision -> decision.set_verdict(candidate_id, verdict, status, org_id)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_record_decision_passes_org_id():
    svc, _, _, decision, _ = _service()
    action = ProposedAction(
        kind=ActionKind.record_decision,
        candidate_ids=[CAND_A],
        params={"verdict": "strong_hire", "status": "hired"},
        summary="s",
        rationale="r",
    )
    await svc.execute(action)
    decision.set_verdict.assert_awaited_once_with(CAND_A, "strong_hire", "hired", ORG_ID)


@pytest.mark.asyncio
async def test_record_decision_without_status_passes_none():
    svc, _, _, decision, _ = _service()
    action = ProposedAction(
        kind=ActionKind.record_decision,
        candidate_ids=[CAND_A],
        params={"verdict": "hire"},
        summary="s",
        rationale="r",
    )
    await svc.execute(action)
    decision.set_verdict.assert_awaited_once_with(CAND_A, "hire", None, ORG_ID)


# ---------------------------------------------------------------------------
# advance_reject -> cr_resolver then decision.set_round_outcome
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_advance_reject_resolves_cr_and_dispatches():
    svc, _, _, decision, cr_resolver = _service()
    action = ProposedAction(
        kind=ActionKind.advance_reject,
        candidate_ids=[CAND_B],
        round_ref="Onsite",
        params={"outcome": "reject"},
        summary="s",
        rationale="r",
    )
    await svc.execute(action)
    cr_resolver.assert_awaited_once_with(CAND_B, "Onsite")
    decision.set_round_outcome.assert_awaited_once_with(RESOLVED_CR, "reject", ORG_ID)


# ---------------------------------------------------------------------------
# log_insight -> DebriefInsightService.log (Phase 3 wired)
# ---------------------------------------------------------------------------
def _insight_mock():
    insight = MagicMock()
    insight.log = AsyncMock(
        return_value={"ok": True, "insight_id": "i1", "sync_status": "synced"}
    )
    return insight


@pytest.mark.asyncio
async def test_log_insight_dispatches_to_insight_service():
    insight = _insight_mock()
    svc, *_ = _service(insight=insight)
    action = ProposedAction(
        kind=ActionKind.log_insight,
        candidate_ids=[CAND_A],
        params={
            "insight_kind": "decision_rationale",
            "text": "Ada won on system design.",
        },
        summary="s",
        rationale="r",
    )
    out = await svc.execute(action)
    assert out["ok"] is True
    assert out["sync_status"] == "synced"
    insight.log.assert_awaited_once()
    kwargs = insight.log.await_args.kwargs
    assert kwargs["organization_id"] == ORG_ID
    assert kwargs["created_by"] == USER_ID
    assert kwargs["candidate_id"] == CAND_A
    assert kwargs["kind"] == "decision_rationale"
    assert kwargs["text"] == "Ada won on system design."
    assert kwargs["packet_id"] == "00000000-0000-0000-0000-0000000000f1"
    assert kwargs["requisition_id"] == REQ_ID


@pytest.mark.asyncio
async def test_log_insight_allows_empty_candidate_ids():
    insight = _insight_mock()
    svc, *_ = _service(insight=insight)
    action = ProposedAction(
        kind=ActionKind.log_insight,
        candidate_ids=[],
        params={
            "insight_kind": "recruiter_preference",
            "text": "This team weights system design.",
            "triplet": {"subject": "PM", "predicate": "values", "object": "SD"},
        },
        summary="s",
        rationale="r",
    )
    out = await svc.execute(action)
    assert out["ok"] is True
    kwargs = insight.log.await_args.kwargs
    assert kwargs["candidate_id"] is None
    assert kwargs["triplet"] == {"subject": "PM", "predicate": "values", "object": "SD"}


@pytest.mark.asyncio
async def test_log_insight_rejects_foreign_candidate():
    insight = _insight_mock()
    svc, *_ = _service(insight=insight)
    action = ProposedAction(
        kind=ActionKind.log_insight,
        candidate_ids=["00000000-0000-0000-0000-0000000000ff"],
        params={"insight_kind": "decision_rationale", "text": "x"},
        summary="s",
        rationale="r",
    )
    with pytest.raises(ValidationError):
        await svc.execute(action)
    insight.log.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_required_param_raises_validation_error_not_keyerror():
    # A well-membership'd action that omits its required param (e.g. a malformed
    # direct POST to /actions) raises ValidationError (-> 400), not KeyError (-> 500).
    svc, feedback, _, _, _ = _service()
    action = ProposedAction(
        kind=ActionKind.request_feedback,
        candidate_ids=[CAND_A],
        round_ref="System Design",
        params={},  # interviewer_email omitted
        summary="s",
        rationale="r",
    )
    with pytest.raises(ValidationError):
        await svc.execute(action)
    feedback.request_feedback.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_log_insight_still_requires_candidate():
    # The empty-candidate allowance is log_insight-only; record_decision still rejects.
    svc, _, _, decision, _ = _service()
    action = ProposedAction(
        kind=ActionKind.record_decision,
        candidate_ids=[],
        params={"verdict": "hire"},
        summary="s",
        rationale="r",
    )
    with pytest.raises(ValidationError):
        await svc.execute(action)
    decision.set_verdict.assert_not_awaited()
