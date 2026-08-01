"""Unit tests for DebriefService — debrief orchestration.

Repository + Cortex client are mocked (constructor-injected). Asserts:
validation (foreign candidate / not-ready), the happy path persists `fresh` via
the supersede RPC, and a Cortex failure flips the row to `failed` AND re-raises a
domain exception (never swallows).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v2.core.exceptions import (
    ConflictError,
    NotFoundError,
    UpstreamServiceError,
    ValidationError,
)
from app.api.v2.services.debrief_service import DebriefService
from app.models.debrief import CandidatePickItem, CandidateSignal

ORG_ID = "00000000-0000-0000-0000-000000000010"
REQ_ID = "00000000-0000-0000-0000-000000000020"
CAND_A = "00000000-0000-0000-0000-0000000000a1"
CAND_B = "00000000-0000-0000-0000-0000000000a2"
CAND_C = "00000000-0000-0000-0000-0000000000a3"
PACKET_ID = "00000000-0000-0000-0000-0000000000f1"
USER_ID = "00000000-0000-0000-0000-000000000002"


def _cand(cid, tier="ready", rated_round_count=None):
    ready = tier == "ready"
    if rated_round_count is None:
        rated_round_count = 1 if ready else 0
    return CandidatePickItem(
        candidate_id=cid, name=cid[-2:], eligibility=tier,
        rounds_completed=1 if ready else 0, rounds_total=1,
        rated_round_count=rated_round_count,
        signal=CandidateSignal(
            feedback_count=2 if ready else 0,
            evidence_backed_count=1 if ready else 0,
        ),
    )


def _make_service(*, candidates, packet=None, client_raises=None):
    repo = MagicMock()
    repo.candidates_for_role = AsyncMock(return_value=candidates)
    repo.insert_generating = AsyncMock(return_value=PACKET_ID)
    repo.finalize_draft = AsyncMock(return_value=None)
    repo.supersede_and_insert = AsyncMock(return_value={"packet_id": PACKET_ID, "status": "fresh"})
    repo.commit_draft = AsyncMock(return_value=None)
    repo.mark_failed = AsyncMock(return_value=None)

    client = MagicMock()
    if client_raises is not None:
        client.generate = AsyncMock(side_effect=client_raises)
    else:
        client.generate = AsyncMock(return_value=packet or {"id": PACKET_ID, "status": "fresh"})

    svc = DebriefService(repository=repo, cortex_client=client)
    return svc, repo, client


def _save_service(*, row):
    """A service wired for save_draft tests: get_packet returns `row` (or None)."""
    repo = MagicMock()
    repo.get_packet = AsyncMock(return_value=row)
    repo.commit_draft = AsyncMock(return_value=None)
    svc = DebriefService(repository=repo, cortex_client=MagicMock())
    return svc, repo


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rejects_foreign_or_unknown_candidate():
    # Only CAND_A is on the role; CAND_C is foreign/unknown.
    svc, repo, client = _make_service(candidates=[_cand(CAND_A), _cand(CAND_B)])
    with pytest.raises(ValidationError):
        await svc.generate(
            org_id=ORG_ID, requisition_id=REQ_ID,
            candidate_ids=[CAND_A, CAND_C], created_by=USER_ID,
        )
    client.generate.assert_not_awaited()
    repo.insert_generating.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejects_non_ready_candidate():
    svc, repo, client = _make_service(
        candidates=[_cand(CAND_A), _cand(CAND_B, tier="awaiting_signal")]
    )
    with pytest.raises(ValidationError):
        await svc.generate(
            org_id=ORG_ID, requisition_id=REQ_ID,
            candidate_ids=[CAND_A, CAND_B], created_by=USER_ID,
        )
    client.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejects_mismatched_rated_round_counts():
    """Parity gate (2026-06-08 §5): two ready candidates with a DIFFERENT number of
    rated rounds (2 vs 3) cannot be co-debriefed — reject before any work."""
    svc, repo, client = _make_service(
        candidates=[
            _cand(CAND_A, rated_round_count=2),
            _cand(CAND_B, rated_round_count=3),
        ]
    )
    with pytest.raises(ValidationError):
        await svc.generate(
            org_id=ORG_ID, requisition_id=REQ_ID,
            candidate_ids=[CAND_A, CAND_B], created_by=USER_ID,
        )
    client.generate.assert_not_awaited()
    repo.insert_generating.assert_not_awaited()


@pytest.mark.asyncio
async def test_accepts_matched_rated_round_counts():
    """Two ready candidates with the SAME rated-round count pass the parity gate."""
    svc, repo, client = _make_service(
        candidates=[
            _cand(CAND_A, rated_round_count=3),
            _cand(CAND_B, rated_round_count=3),
        ]
    )
    out = await svc.generate(
        org_id=ORG_ID, requisition_id=REQ_ID,
        candidate_ids=[CAND_A, CAND_B], created_by=USER_ID,
    )
    assert out["status"] == "draft"
    client.generate.assert_awaited_once()


# ---------------------------------------------------------------------------
# Happy path — generate lands a DRAFT (no supersede)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_happy_path_persists_draft_without_supersede():
    """generate now finalizes the packet to `draft` (previewable, not kept) and
    does NOT supersede the prior fresh — that happens only on an explicit save."""
    packet = {"id": PACKET_ID, "status": "fresh", "verdict": "hire"}
    svc, repo, client = _make_service(
        candidates=[_cand(CAND_A), _cand(CAND_B)], packet=packet
    )
    out = await svc.generate(
        org_id=ORG_ID, requisition_id=REQ_ID,
        candidate_ids=[CAND_A, CAND_B], created_by=USER_ID,
    )
    assert out["packet_id"] == PACKET_ID
    assert out["status"] == "draft"
    repo.insert_generating.assert_awaited_once()
    client.generate.assert_awaited_once()
    # finalize_draft persists the cortex packet verbatim — NOT supersede_and_insert
    repo.finalize_draft.assert_awaited_once()
    assert repo.finalize_draft.call_args.args[0] == PACKET_ID
    assert repo.finalize_draft.call_args.args[1] == packet
    repo.supersede_and_insert.assert_not_awaited()
    repo.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_overwrites_packet_body_id_with_row_id():
    """Regression (live-DB ID-mismatch bug): the Cortex skill stamps its OWN id on
    the packet body (a uuid != the debrief_packets row id). If that body id is
    persisted verbatim, the FE threads it into Save/Download and POST
    /packets/{cortex_id}/save + GET /packets/{cortex_id} 404. generate MUST rewrite
    the body id to the generating-row id so the stored packet is addressable by the
    same id /generate returns."""
    CORTEX_BODY_ID = "00000000-0000-0000-0000-0000000000cc"  # != PACKET_ID (row id)
    packet = {"id": CORTEX_BODY_ID, "status": "fresh", "verdict": "hire"}
    svc, repo, client = _make_service(
        candidates=[_cand(CAND_A), _cand(CAND_B)], packet=packet
    )
    await svc.generate(
        org_id=ORG_ID, requisition_id=REQ_ID,
        candidate_ids=[CAND_A, CAND_B], created_by=USER_ID,
    )
    finalized_packet = repo.finalize_draft.call_args.args[1]
    # the persisted body id == the generating row id (NOT the cortex body id)
    assert finalized_packet["id"] == PACKET_ID
    assert finalized_packet["id"] != CORTEX_BODY_ID
    # other body fields are untouched
    assert finalized_packet["verdict"] == "hire"
    assert finalized_packet["status"] == "fresh"


# ---------------------------------------------------------------------------
# save_draft — commit draft -> fresh
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_draft_commits_draft_to_fresh():
    svc, repo = _save_service(
        row={"id": PACKET_ID, "status": "draft", "organization_id": ORG_ID}
    )
    out = await svc.save_draft(org_id=ORG_ID, packet_id=PACKET_ID)
    assert out == {"packet_id": PACKET_ID, "status": "fresh"}
    repo.commit_draft.assert_awaited_once_with(PACKET_ID)


@pytest.mark.asyncio
async def test_save_draft_idempotent_when_already_fresh():
    """Saving a packet that is already fresh is a no-op success (no RPC)."""
    svc, repo = _save_service(
        row={"id": PACKET_ID, "status": "fresh", "organization_id": ORG_ID}
    )
    out = await svc.save_draft(org_id=ORG_ID, packet_id=PACKET_ID)
    assert out == {"packet_id": PACKET_ID, "status": "fresh"}
    repo.commit_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_draft_missing_raises_not_found():
    svc, repo = _save_service(row=None)  # cross-org or missing
    with pytest.raises(NotFoundError):
        await svc.save_draft(org_id=ORG_ID, packet_id=PACKET_ID)
    repo.commit_draft.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["generating", "failed"])
async def test_save_draft_conflict_for_generating_or_failed(status):
    svc, repo = _save_service(
        row={"id": PACKET_ID, "status": status, "organization_id": ORG_ID}
    )
    with pytest.raises(ConflictError):
        await svc.save_draft(org_id=ORG_ID, packet_id=PACKET_ID)
    repo.commit_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_draft_conflict_for_superseded():
    """A superseded packet cannot be re-saved (it lost its natural-key slot)."""
    svc, repo = _save_service(
        row={"id": PACKET_ID, "status": "superseded", "organization_id": ORG_ID}
    )
    with pytest.raises(ConflictError):
        await svc.save_draft(org_id=ORG_ID, packet_id=PACKET_ID)
    repo.commit_draft.assert_not_awaited()


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cortex_failure_marks_failed_and_raises():
    svc, repo, client = _make_service(
        candidates=[_cand(CAND_A), _cand(CAND_B)],
        client_raises=UpstreamServiceError("boom"),
    )
    with pytest.raises(UpstreamServiceError):
        await svc.generate(
            org_id=ORG_ID, requisition_id=REQ_ID,
            candidate_ids=[CAND_A, CAND_B], created_by=USER_ID,
        )
    repo.insert_generating.assert_awaited_once()
    repo.mark_failed.assert_awaited_once()
    assert repo.mark_failed.call_args.args[0] == PACKET_ID
    repo.finalize_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_marks_failed_with_static_message_not_raw():
    svc, repo, client = _make_service(
        candidates=[_cand(CAND_A), _cand(CAND_B)],
        client_raises=RuntimeError("secret-internal-detail"),
    )
    with pytest.raises(UpstreamServiceError):
        await svc.generate(
            org_id=ORG_ID, requisition_id=REQ_ID,
            candidate_ids=[CAND_A, CAND_B], created_by=USER_ID,
        )
    # the persisted generation_error must NOT leak the raw exception text
    err_msg = repo.mark_failed.call_args.args[1]
    assert "secret-internal-detail" not in err_msg


@pytest.mark.asyncio
async def test_finalize_failure_marks_failed_and_no_sqlstate_leak():
    """An error from finalize_draft (e.g. an uncatalogued PostgrestError surfaced
    as UpstreamServiceError('RPC error: <SQLSTATE> <raw pg msg>')) must NOT escape
    to the client, the row must NOT stay `generating` (mark_failed runs), and a
    STATIC domain message is re-raised."""
    svc, repo, client = _make_service(candidates=[_cand(CAND_A), _cand(CAND_B)])
    repo.finalize_draft = AsyncMock(
        side_effect=UpstreamServiceError(
            "RPC error: 40P01 deadlock detected on debrief_packets"
        )
    )

    with pytest.raises(UpstreamServiceError) as exc_info:
        await svc.generate(
            org_id=ORG_ID, requisition_id=REQ_ID,
            candidate_ids=[CAND_A, CAND_B], created_by=USER_ID,
        )

    # the row must be flipped out of `generating` with a static message
    repo.mark_failed.assert_awaited_once()
    assert repo.mark_failed.call_args.args[0] == PACKET_ID
    static_persisted = repo.mark_failed.call_args.args[1]
    assert "40P01" not in static_persisted
    assert "deadlock" not in static_persisted

    # the client-visible message must be static — no SQLSTATE / raw pg text leak
    client_msg = str(exc_info.value)
    assert "40P01" not in client_msg
    assert "deadlock" not in client_msg
    assert "RPC error" not in client_msg


@pytest.mark.asyncio
async def test_dedups_candidate_ids_before_validation():
    # Duplicate ids collapse; the unique set is {A, B} (2 valid).
    svc, repo, client = _make_service(candidates=[_cand(CAND_A), _cand(CAND_B)])
    await svc.generate(
        org_id=ORG_ID, requisition_id=REQ_ID,
        candidate_ids=[CAND_A, CAND_A, CAND_B], created_by=USER_ID,
    )
    persisted = repo.insert_generating.call_args.kwargs["candidate_ids"]
    assert sorted(persisted) == sorted([CAND_A, CAND_B])
