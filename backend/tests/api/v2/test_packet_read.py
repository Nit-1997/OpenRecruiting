"""
Tests for the candidate packet read RPC contract.

Exercises GET /api/v2/roles/{id}/candidates/{cid}/packet, a pure pass-through
to the `get_candidate_packet` SQL function (migration 81, patched by 85).
The RPC returns `{candidate, rounds}` JSONB and is the single source of
truth for the packet drawer; this file pins the wire contract.

These tests mock the RPC itself — they DO NOT exercise the Postgres
function. Migration 85 explicitly fixed missing `candidate_id` / `round_id`
keys on each candidate_round in the packet payload, so this file asserts
those keys appear in the response (regression guard).
"""

import httpx

from tests.helpers.mock_data import (
    REQ_ID,
    CANDIDATE_ID,
    ROUND_ID,
    CANDIDATE_ROUND_ID,
)
from tests.helpers.supabase_mocks import rpc_url


V2_ROOT = "/api/v2"


def _make_packet_payload(candidate_id=CANDIDATE_ID):
    """Build the JSONB shape the `get_candidate_packet` RPC actually returns.
    Mirrors `deploy-config/sql/81-role-detail-v2.sql` (the `jsonb_build_object`
    near lines 214-261) and migration 85's CR-key patch.

    Top-level: `{candidate, rounds: [{round, candidate_round, feedback_questions, assessment, recording}]}`
    The drawer consumes `r.round.id` and `r.candidate_round.id` — these
    tests pin that shape so a refactor can't silently flatten it.
    """
    return {
        "candidate": {
            "id": candidate_id,
            "name": "Aanya Ellis",
            "email": "aanya@example.com",
            "status": "active",
            "final_verdict": None,
            "created_at": "2026-05-18T10:00:00+00:00",
            "requisition_id": REQ_ID,
        },
        "rounds": [
            {
                "round": {
                    "id": ROUND_ID,
                    "requisition_id": REQ_ID,
                    "round_number": 1,
                    "name": "Tech Screen",
                    "category": "coding",
                    "duration_minutes": 45,
                    "description": None,
                    "skills": [],
                    "guidelines": [],
                    "is_custom": False,
                    "for_candidate_id": None,
                    "removed_from_plan_at": None,
                },
                "candidate_round": {
                    "id": CANDIDATE_ROUND_ID,
                    # Migration 85 added these two — the drawer and the FE's
                    # resolveCrIdFromPacket helper depend on candidate_id +
                    # round_id appearing here.
                    "candidate_id": candidate_id,
                    "round_id": ROUND_ID,
                    "status": "completed",
                    "scorecard_status": "complete",
                    "rating": 4,
                    "summary": "Solid problem solving.",
                    "question_summaries": {},
                    "scheduled_at": "2026-05-19T10:00:00+00:00",
                    "completed_at": "2026-05-19T11:00:00+00:00",
                    "interviewer_email": "jane@example.com",
                    "interviewer_name": "Jane Recruiter",
                    "meeting_url": None,
                },
                "feedback_questions": [],
                "assessment": None,
                "recording": {
                    "status": "done",
                    "duration_seconds": 1800,
                    "has_transcript": True,
                },
            },
        ],
    }


def test_get_candidate_packet_returns_full_payload(recruiter_client, respx_mock):
    """Happy path: RPC returns candidate + rounds, the service is a
    pass-through, response mirrors the RPC payload."""
    respx_mock.post(rpc_url("get_candidate_packet")).mock(
        return_value=httpx.Response(200, json=_make_packet_payload())
    )

    resp = recruiter_client.get(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/packet"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["candidate"]["id"] == CANDIDATE_ID
    assert body["candidate"]["name"] == "Aanya Ellis"
    assert isinstance(body["rounds"], list)
    assert len(body["rounds"]) == 1

    rnd_wrapper = body["rounds"][0]
    # Shape contract: nested round + candidate_round, not a flat row.
    assert rnd_wrapper["round"]["id"] == ROUND_ID
    assert rnd_wrapper["round"]["round_number"] == 1

    cr = rnd_wrapper["candidate_round"]
    # Migration 85 contract: candidate_id + round_id on each CR payload.
    # This is the regression guard for the bug that 85 fixed — without
    # these the FE drawer's resolveCrIdFromPacket helper would never find
    # the cr_id to schedule/cancel/feedback against.
    assert cr["id"] == CANDIDATE_ROUND_ID
    assert cr["candidate_id"] == CANDIDATE_ID
    assert cr["round_id"] == ROUND_ID
    assert cr["status"] == "completed"
    assert cr["rating"] == 4


def test_get_candidate_packet_404_when_candidate_null(recruiter_client, respx_mock):
    """RPC returns `{candidate: null, rounds: null}` for a missing or
    cross-org candidate. Service translates that to 404 so the drawer can
    surface a sensible empty state instead of rendering with null."""
    respx_mock.post(rpc_url("get_candidate_packet")).mock(
        return_value=httpx.Response(
            200,
            json={"candidate": None, "rounds": None},
        )
    )

    resp = recruiter_client.get(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/packet"
    )
    assert resp.status_code == 404


def test_get_candidate_packet_404_when_rpc_returns_empty(recruiter_client, respx_mock):
    """RPC may return an empty JSON object on edge cases (no row from the
    aggregation CTE). Treat the same way as a missing candidate."""
    respx_mock.post(rpc_url("get_candidate_packet")).mock(
        return_value=httpx.Response(200, json={})
    )

    resp = recruiter_client.get(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/packet"
    )
    assert resp.status_code == 404


def test_get_candidate_packet_preserves_recording_subobject(recruiter_client, respx_mock):
    """`recording.has_transcript` is the flag the drawer uses to decide
    whether to fetch the transcript GET endpoint. Confirm it survives the
    pass-through layer untouched — flattening this would break the drawer."""
    payload = _make_packet_payload()
    payload["rounds"][0]["recording"] = {
        "status": "done",
        "duration_seconds": 1800,
        "has_transcript": False,
    }
    respx_mock.post(rpc_url("get_candidate_packet")).mock(
        return_value=httpx.Response(200, json=payload)
    )

    resp = recruiter_client.get(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/packet"
    )
    assert resp.status_code == 200
    rec = resp.json()["rounds"][0]["recording"]
    assert rec["has_transcript"] is False
    assert rec["status"] == "done"


def test_get_candidate_packet_403_when_no_org(unauthed_client, respx_mock):
    """The endpoint requires a user with an organization. The RPC must not
    be called when org is missing."""
    # Intentionally do NOT mock the RPC — if the endpoint reaches it, the
    # mock will assert_all_mocked guard fires.
    from app.main import app
    from app.dependencies import get_current_user, CurrentUser
    from uuid import UUID
    from tests.helpers.mock_data import RECRUITER_USER_ID

    no_org_user = CurrentUser(
        id=UUID(RECRUITER_USER_ID),
        email="recruiter@test.com",
        is_staff=False,
        organization_id=None,
    )
    app.dependency_overrides[get_current_user] = lambda: no_org_user
    try:
        resp = unauthed_client.get(
            f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/packet"
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
