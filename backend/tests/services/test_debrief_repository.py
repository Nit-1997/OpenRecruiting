"""Unit tests for DebriefRepository — the Supabase data layer for debrief.

The DB boundary is a fluent MagicMock (mirrors test_screening_invite_service.py).
Every method must go through execute_async / count_async / rpc — no sync .execute()
on the event loop. Eligibility tiering is pure logic over the embedded rounds, so
it's asserted directly against shaped rows.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v2.core.exceptions import UpstreamServiceError
from app.api.v2.services.debrief_repository import DebriefRepository

ORG_ID = "00000000-0000-0000-0000-000000000010"
REQ_ID = "00000000-0000-0000-0000-000000000020"
CAND_A = "00000000-0000-0000-0000-0000000000a1"
CAND_B = "00000000-0000-0000-0000-0000000000a2"
CAND_C = "00000000-0000-0000-0000-0000000000a3"
PACKET_ID = "00000000-0000-0000-0000-0000000000f1"


def _fluent(return_data):
    """A fluent Supabase builder whose execute_async yields `return_data`."""
    builder = MagicMock()
    for m in (
        "table", "select", "insert", "update", "delete", "eq", "neq", "in_",
        "is_", "is_null", "not_null", "limit", "order", "single", "contains",
    ):
        getattr(builder, m).return_value = builder
    builder.execute_async = AsyncMock(return_value=MagicMock(data=return_data))
    builder.count_async = AsyncMock(return_value=0)
    supa = MagicMock()
    supa.table.return_value = builder
    supa.rpc = AsyncMock(return_value=MagicMock(data={"packet_id": PACKET_ID, "status": "fresh"}))
    return supa, builder


def _round(*, completed=True, rating="yes", feedback=None):
    """A candidate_rounds row with its rating + nested candidate_feedback embed."""
    return {
        "processing_status": "completed" if completed else "none",
        "status": "completed" if completed else "scheduled",
        "rating": rating,
        "candidate_feedback": feedback or [],
    }


# ---------------------------------------------------------------------------
# Eligibility tiering — rating-based classification (spec 2026-06-08 §5)
# ---------------------------------------------------------------------------
def test_classify_ready_when_completed_round_is_rated():
    """ready requires a completed round carrying a valid rating (the scoring
    signal) — feedback rows are NOT required for the rating-based score."""
    rounds = [
        _round(completed=True, rating="yes", feedback=[]),
        _round(completed=False),
    ]
    assert DebriefRepository._eligibility(rounds) == "ready"
    assert DebriefRepository._rated_round_count(rounds) == 1


def test_classify_awaiting_signal_when_completed_round_has_no_rating():
    """A completed round with NO rating is awaiting_signal — it can't be scored."""
    rounds = [_round(completed=True, rating=None)]
    assert DebriefRepository._eligibility(rounds) == "awaiting_signal"
    assert DebriefRepository._rated_round_count(rounds) == 0


def test_rated_round_count_counts_only_completed_and_rated():
    rounds = [
        _round(completed=True, rating="strong_yes"),
        _round(completed=True, rating="no"),
        _round(completed=True, rating=None),   # completed but unrated → excluded
        _round(completed=False, rating="yes"),  # rated but not completed → excluded
    ]
    assert DebriefRepository._rated_round_count(rounds) == 2


def test_classify_awaiting_signal_when_rounds_but_none_completed():
    rounds = [_round(completed=False)]
    assert DebriefRepository._eligibility(rounds) == "awaiting_signal"


def test_classify_early_stage_when_no_rounds():
    assert DebriefRepository._eligibility([]) == "early_stage"


# ---------------------------------------------------------------------------
# Signal — feedback_count + evidence_backed_count across the candidate's rounds
# ---------------------------------------------------------------------------
def test_signal_counts_feedback_and_evidence_backed():
    rounds = [
        _round(
            completed=True,
            feedback=[
                {"evidence_status": "verified"},
                {"evidence_status": None},  # not evidence-backed
                {"evidence_status": "supported"},
            ],
        ),
        _round(completed=False, feedback=[{"evidence_status": "partial"}]),
    ]
    sig = DebriefRepository._signal(rounds)
    assert sig.feedback_count == 4
    assert sig.evidence_backed_count == 3  # verified, supported, partial (None excluded)


def test_signal_zero_when_no_feedback():
    sig = DebriefRepository._signal([_round(completed=True, feedback=[])])
    assert sig.feedback_count == 0
    assert sig.evidence_backed_count == 0


# ---------------------------------------------------------------------------
# candidates_for_role — org-scoped, returns picker items with tiers
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_candidates_for_role_tiers_and_org_scope():
    rows = [
        {
            "id": CAND_A, "name": "Ada", "requisition_id": REQ_ID,
            "requisitions": {"organization_id": ORG_ID, "deleted_at": None},
            "candidate_rounds": [
                _round(completed=True, feedback=[
                    {"evidence_status": "verified"},
                    {"evidence_status": None},
                ]),
                _round(completed=False),
            ],
        },
        {
            "id": CAND_B, "name": "Bob", "requisition_id": REQ_ID,
            "requisitions": {"organization_id": ORG_ID, "deleted_at": None},
            "candidate_rounds": [],
        },
    ]
    supa, _ = _fluent(rows)
    repo = DebriefRepository(supa)
    out = await repo.candidates_for_role(REQ_ID, ORG_ID)
    by_id = {c.candidate_id: c for c in out}
    assert by_id[CAND_A].eligibility == "ready"
    assert by_id[CAND_A].rounds_completed == 1
    assert by_id[CAND_A].rounds_total == 2
    assert by_id[CAND_A].rated_round_count == 1
    assert by_id[CAND_A].signal.feedback_count == 2
    assert by_id[CAND_A].signal.evidence_backed_count == 1
    assert by_id[CAND_B].eligibility == "early_stage"
    assert by_id[CAND_B].rated_round_count == 0
    assert by_id[CAND_B].signal.feedback_count == 0


@pytest.mark.asyncio
async def test_candidates_for_role_completed_unrated_is_awaiting_signal():
    """A completed round with no rating can't be scored → awaiting_signal (NOT
    ready), with a zero rated_round_count."""
    rows = [
        {
            "id": CAND_A, "name": "Ada", "requisition_id": REQ_ID,
            "requisitions": {"organization_id": ORG_ID, "deleted_at": None},
            "candidate_rounds": [_round(completed=True, rating=None, feedback=[])],
        },
    ]
    supa, _ = _fluent(rows)
    repo = DebriefRepository(supa)
    out = await repo.candidates_for_role(REQ_ID, ORG_ID)
    assert out[0].eligibility == "awaiting_signal"
    assert out[0].rated_round_count == 0


@pytest.mark.asyncio
async def test_candidates_for_role_excludes_foreign_org():
    rows = [
        {
            "id": CAND_C, "name": "Eve", "requisition_id": REQ_ID,
            "requisitions": {"organization_id": "other-org", "deleted_at": None},
            "candidate_rounds": [_round(completed=True, feedback=[{"evidence_status": "verified"}])],
        },
    ]
    supa, _ = _fluent(rows)
    repo = DebriefRepository(supa)
    out = await repo.candidates_for_role(REQ_ID, ORG_ID)
    assert out == []


# ---------------------------------------------------------------------------
# roles_with_eligible_candidates — only roles with >= 2 ready candidates
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_roles_with_eligible_candidates_filters_under_two():
    # Two reqs: REQ_ID has 2 ready candidates, the other has 1.
    other_req = "00000000-0000-0000-0000-000000000021"
    ready_round = _round(completed=True, feedback=[{"evidence_status": "verified"}])
    rows = [
        {"id": CAND_A, "requisition_id": REQ_ID,
         "requisitions": {"id": REQ_ID, "role_title": "PM", "organization_id": ORG_ID, "deleted_at": None},
         "candidate_rounds": [ready_round]},
        {"id": CAND_B, "requisition_id": REQ_ID,
         "requisitions": {"id": REQ_ID, "role_title": "PM", "organization_id": ORG_ID, "deleted_at": None},
         "candidate_rounds": [ready_round]},
        {"id": CAND_C, "requisition_id": other_req,
         "requisitions": {"id": other_req, "role_title": "EM", "organization_id": ORG_ID, "deleted_at": None},
         "candidate_rounds": [ready_round]},
    ]
    supa, _ = _fluent(rows)
    repo = DebriefRepository(supa)
    out = await repo.roles_with_eligible_candidates(ORG_ID)
    assert len(out) == 1
    assert out[0].requisition_id == REQ_ID
    assert out[0].role_title == "PM"
    assert out[0].eligible_candidate_count == 2


@pytest.mark.asyncio
async def test_roles_excludes_role_whose_completed_candidates_lack_rating():
    """A role with 2 completed-but-UNRATED candidates has 0 ready → dropped."""
    unrated_round = _round(completed=True, rating=None)
    rows = [
        {"id": CAND_A, "requisition_id": REQ_ID,
         "requisitions": {"id": REQ_ID, "role_title": "PM", "organization_id": ORG_ID, "deleted_at": None},
         "candidate_rounds": [unrated_round]},
        {"id": CAND_B, "requisition_id": REQ_ID,
         "requisitions": {"id": REQ_ID, "role_title": "PM", "organization_id": ORG_ID, "deleted_at": None},
         "candidate_rounds": [unrated_round]},
    ]
    supa, _ = _fluent(rows)
    repo = DebriefRepository(supa)
    out = await repo.roles_with_eligible_candidates(ORG_ID)
    assert out == []


@pytest.mark.asyncio
async def test_roles_excludes_role_when_ready_candidates_have_mismatched_counts():
    """Parity (2026-06-08 §5): 2 ready candidates but with DIFFERENT rated-round
    counts (1 vs 2) cannot be co-debriefed → the role is NOT offered."""
    one_round = [_round(completed=True, rating="yes")]
    two_rounds = [_round(completed=True, rating="yes"), _round(completed=True, rating="no")]
    rows = [
        {"id": CAND_A, "requisition_id": REQ_ID,
         "requisitions": {"id": REQ_ID, "role_title": "PM", "organization_id": ORG_ID, "deleted_at": None},
         "candidate_rounds": one_round},
        {"id": CAND_B, "requisition_id": REQ_ID,
         "requisitions": {"id": REQ_ID, "role_title": "PM", "organization_id": ORG_ID, "deleted_at": None},
         "candidate_rounds": two_rounds},
    ]
    supa, _ = _fluent(rows)
    repo = DebriefRepository(supa)
    out = await repo.roles_with_eligible_candidates(ORG_ID)
    assert out == []


@pytest.mark.asyncio
async def test_roles_offered_when_two_ready_share_the_same_count():
    """3 ready candidates: two share count 2, one has count 1 → the role is offered
    with eligible_candidate_count = 2 (the largest parity-matched group)."""
    one_round = [_round(completed=True, rating="yes")]
    two_rounds = [_round(completed=True, rating="yes"), _round(completed=True, rating="no")]
    rows = [
        {"id": CAND_A, "requisition_id": REQ_ID,
         "requisitions": {"id": REQ_ID, "role_title": "PM", "organization_id": ORG_ID, "deleted_at": None},
         "candidate_rounds": two_rounds},
        {"id": CAND_B, "requisition_id": REQ_ID,
         "requisitions": {"id": REQ_ID, "role_title": "PM", "organization_id": ORG_ID, "deleted_at": None},
         "candidate_rounds": two_rounds},
        {"id": CAND_C, "requisition_id": REQ_ID,
         "requisitions": {"id": REQ_ID, "role_title": "PM", "organization_id": ORG_ID, "deleted_at": None},
         "candidate_rounds": one_round},
    ]
    supa, _ = _fluent(rows)
    repo = DebriefRepository(supa)
    out = await repo.roles_with_eligible_candidates(ORG_ID)
    assert len(out) == 1
    assert out[0].eligible_candidate_count == 2


# ---------------------------------------------------------------------------
# insert_generating / mark_failed / supersede_and_insert
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_insert_generating_returns_packet_id():
    supa, builder = _fluent(None)
    # insert(...).execute_async() chain
    insert_builder = MagicMock()
    insert_builder.execute_async = AsyncMock(return_value=MagicMock(data={"id": PACKET_ID}))
    builder.insert.return_value = insert_builder
    repo = DebriefRepository(supa)
    pid = await repo.insert_generating(
        requisition_id=REQ_ID, organization_id=ORG_ID,
        created_by="00000000-0000-0000-0000-000000000002",
        candidate_ids=[CAND_A, CAND_B],
    )
    assert pid == PACKET_ID
    builder.insert.assert_called_once()
    payload = builder.insert.call_args.args[0]
    assert payload["status"] == "generating"
    assert payload["candidate_ids"] == [CAND_A, CAND_B]


@pytest.mark.asyncio
@pytest.mark.parametrize("returned", [None, {}, {"status": "generating"}])
async def test_insert_generating_raises_domain_error_when_no_id(returned):
    """FIX 5a: a missing/empty insert response must raise a domain
    UpstreamServiceError (mapped to a clean 502), not a bare KeyError → 500."""
    supa, builder = _fluent(None)
    insert_builder = MagicMock()
    insert_builder.execute_async = AsyncMock(return_value=MagicMock(data=returned))
    builder.insert.return_value = insert_builder
    repo = DebriefRepository(supa)
    with pytest.raises(UpstreamServiceError):
        await repo.insert_generating(
            requisition_id=REQ_ID, organization_id=ORG_ID,
            created_by=None, candidate_ids=[CAND_A, CAND_B],
        )


def test_mark_ready_method_is_removed():
    """FIX 5b: the dead, never-called `mark_ready` finalize path is deleted.
    `supersede_and_insert` is the single finalize path."""
    assert not hasattr(DebriefRepository, "mark_ready")


@pytest.mark.asyncio
async def test_supersede_and_insert_calls_rpc():
    supa, _ = _fluent(None)
    repo = DebriefRepository(supa)
    packet = {"id": PACKET_ID, "verdict": "hire"}
    await repo.supersede_and_insert(packet_id=PACKET_ID, packet=packet)
    supa.rpc.assert_awaited_once()
    name, params = supa.rpc.call_args.args
    assert name == "debrief_supersede_and_insert"
    assert params["p"]["packet_id"] == PACKET_ID
    assert params["p"]["packet"] == packet


# ---------------------------------------------------------------------------
# finalize_draft / commit_draft (Phase 1 — draft -> save lifecycle)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_finalize_draft_writes_draft_status_and_packet():
    """generate's non-superseding finalize: flip the `generating` row to `draft`
    with the packet JSONB + generated_at stamped (NO supersede here)."""
    supa, builder = _fluent(None)
    update_builder = MagicMock()
    update_builder.eq.return_value = update_builder
    update_builder.execute_async = AsyncMock(return_value=MagicMock(data=None))
    builder.update.return_value = update_builder
    repo = DebriefRepository(supa)
    packet = {"id": PACKET_ID, "verdict": "hire"}
    await repo.finalize_draft(PACKET_ID, packet)
    builder.update.assert_called_once()
    payload = builder.update.call_args.args[0]
    assert payload["status"] == "draft"
    assert payload["packet"] == packet
    assert payload["generated_at"] is not None
    assert payload["updated_at"] is not None
    # scoped to the target row
    update_builder.eq.assert_called_once_with("id", PACKET_ID)
    # finalize_draft must NOT touch the supersede RPC
    supa.rpc.assert_not_awaited()


@pytest.mark.asyncio
async def test_commit_draft_calls_commit_rpc_with_id():
    supa, _ = _fluent(None)
    repo = DebriefRepository(supa)
    await repo.commit_draft(PACKET_ID)
    supa.rpc.assert_awaited_once()
    name, params = supa.rpc.call_args.args
    assert name == "debrief_commit_draft"
    assert params["p_packet_id"] == PACKET_ID


@pytest.mark.asyncio
async def test_mark_failed_updates_status_and_error():
    supa, builder = _fluent(None)
    update_builder = MagicMock()
    update_builder.eq.return_value = update_builder
    update_builder.execute_async = AsyncMock(return_value=MagicMock(data=None))
    builder.update.return_value = update_builder
    repo = DebriefRepository(supa)
    await repo.mark_failed(PACKET_ID, "cortex unreachable")
    builder.update.assert_called_once()
    payload = builder.update.call_args.args[0]
    assert payload["status"] == "failed"
    assert payload["generation_error"] == "cortex unreachable"


# ---------------------------------------------------------------------------
# get_packet / list_packets — org-scoped reads
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_packet_returns_row_when_org_matches():
    row = {"id": PACKET_ID, "organization_id": ORG_ID, "status": "fresh",
           "packet": {"id": PACKET_ID}, "requisition_id": REQ_ID}
    supa, _ = _fluent(row)
    repo = DebriefRepository(supa)
    out = await repo.get_packet(PACKET_ID, ORG_ID)
    assert out["id"] == PACKET_ID


@pytest.mark.asyncio
async def test_get_packet_none_for_foreign_org():
    supa, _ = _fluent(None)  # single() -> no rows -> None
    repo = DebriefRepository(supa)
    out = await repo.get_packet(PACKET_ID, ORG_ID)
    assert out is None


@pytest.mark.asyncio
async def test_list_packets_returns_items_newest_first():
    rows = [
        {"id": PACKET_ID, "status": "fresh", "candidate_ids": [CAND_A, CAND_B],
         "packet": {"verdict": "hire", "confidence": "high", "generated_at": "2026-06-07T10:00:00Z"},
         "created_at": "2026-06-07T10:00:00Z", "generated_at": "2026-06-07T10:00:00Z"},
        {"id": "p2", "status": "superseded", "candidate_ids": [CAND_A],
         "packet": None, "created_at": "2026-06-06T10:00:00Z", "generated_at": None},
    ]
    supa, _ = _fluent(rows)
    repo = DebriefRepository(supa)
    out = await repo.list_packets(REQ_ID, ORG_ID)
    assert len(out) == 2
    assert out[0].packet_id == PACKET_ID
    assert out[0].verdict == "hire"
    assert out[0].confidence == "high"
    assert out[1].verdict is None


@pytest.mark.asyncio
async def test_list_packets_filters_out_drafts():
    """The role packet list shows only committed packets (fresh/superseded);
    drafts/generating/failed are excluded via a status .in_ filter."""
    supa, builder = _fluent([])
    repo = DebriefRepository(supa)
    await repo.list_packets(REQ_ID, ORG_ID)
    builder.in_.assert_called_once_with("status", ["fresh", "superseded"])
