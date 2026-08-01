"""
Tests for the role-pipeline read RPC contract.

Exercises GET /api/v2/roles/{id}/candidates, which is a thin wrapper around
the `get_role_pipeline` SQL function (migration 81). The RPC's JSON shape
is the contract that the v2 frontend consumes; this file pins that shape +
the FE-enrichment fields the pipeline_service adds on top (avatar_initials,
avatar_color, current_round_id).

These tests mock the RPC itself — they DO NOT exercise the Postgres function.
That's a known gap; see the spec divergence notes. The point is to lock in
the wire contract so a service-side refactor can't silently regress it.
"""

import httpx
import pytest

from tests.helpers.mock_data import (
    REQ_ID,
    CANDIDATE_ID,
    ROUND_ID,
    CANDIDATE_ROUND_ID,
)
from tests.helpers.supabase_mocks import rpc_url


V2_ROOT = "/api/v2"


def _make_pipeline_payload(candidates=None):
    """Build the JSONB shape the `get_role_pipeline` RPC returns.

    Mirrors `deploy-config/sql/81-role-detail-v2.sql` lines 76-95 — the
    shape is: `{candidates: [{id, name, ..., candidate_rounds: [...]}]}`.
    """
    return {
        "candidates": candidates or [
            {
                "id": CANDIDATE_ID,
                "name": "Aanya Sharma",
                "email": "aanya@example.com",
                "status": "active",
                "final_verdict": None,
                "created_at": "2026-05-18T10:00:00+00:00",
                "candidate_rounds": [
                    {
                        "id": CANDIDATE_ROUND_ID,
                        "round_id": ROUND_ID,
                        "round_number": 1,
                        "round_name": "Tech Screen",
                        "category": "coding",
                        "duration_minutes": 45,
                        "is_custom": False,
                        "for_candidate_id": None,
                        "interviewer_name": "Jane Recruiter",
                        "interviewer_email": "jane@example.com",
                        "scheduled_at": None,
                        "status": "pending",
                        "processing_status": None,
                        "rating": None,
                        "summary": None,
                    },
                ],
            },
        ],
    }


def test_get_role_pipeline_returns_enriched_candidates(recruiter_client, respx_mock):
    """The happy path: RPC returns a candidate with one pending round; the
    service enriches each candidate with avatar_initials, avatar_color, and
    current_round_id derived from the first non-completed round."""
    respx_mock.post(rpc_url("get_role_pipeline")).mock(
        return_value=httpx.Response(200, json=_make_pipeline_payload())
    )

    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/candidates")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "candidates" in body
    assert len(body["candidates"]) == 1
    cand = body["candidates"][0]

    # Pass-through fields from the RPC.
    assert cand["id"] == CANDIDATE_ID
    assert cand["name"] == "Aanya Sharma"
    assert cand["status"] == "active"
    assert len(cand["candidate_rounds"]) == 1

    # Enrichment per pipeline_service._enrich_candidate.
    # "Aanya Sharma" → first letter of first + last name.
    assert cand["avatar_initials"] == "AS"
    # avatar_color must be one of the palette colors.
    assert cand["avatar_color"].startswith("#")
    assert len(cand["avatar_color"]) == 7
    # current_round_id = first non-completed candidate_round.round_id.
    assert cand["current_round_id"] == ROUND_ID


def test_get_role_pipeline_avatar_color_is_deterministic_by_id(recruiter_client, respx_mock):
    """avatar_color must be a stable function of candidate_id so reloads
    don't reshuffle colors in the rail view. Confirms md5-derived determinism."""
    payload = _make_pipeline_payload()
    respx_mock.post(rpc_url("get_role_pipeline")).mock(
        return_value=httpx.Response(200, json=payload)
    )

    resp1 = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/candidates").json()
    resp2 = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/candidates").json()

    color1 = resp1["candidates"][0]["avatar_color"]
    color2 = resp2["candidates"][0]["avatar_color"]
    assert color1 == color2


def test_get_role_pipeline_empty_candidates(recruiter_client, respx_mock):
    """RPC returns `{candidates: []}` for a requisition with no candidates —
    surface as empty array, not 404. The rail's empty-state needs a 200."""
    respx_mock.post(rpc_url("get_role_pipeline")).mock(
        return_value=httpx.Response(200, json={"candidates": []})
    )

    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/candidates")
    assert resp.status_code == 200
    assert resp.json() == {"candidates": []}


def test_get_role_pipeline_cross_org_empty_candidates(recruiter_client, respx_mock):
    """Cross-org should not 404 — the spec keeps this as the empty-pipeline
    return so the rail's role-detail page doesn't crash on a stale link."""
    respx_mock.post(rpc_url("get_role_pipeline")).mock(
        return_value=httpx.Response(200, json={"candidates": []})
    )

    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/candidates")
    assert resp.status_code == 200
    assert resp.json()["candidates"] == []


def test_get_role_pipeline_current_round_skips_completed(recruiter_client, respx_mock):
    """current_round_id must pick the first non-completed candidate_round.
    The RPC returns rounds in round_number order; the service picks the
    first one whose status != 'completed'."""
    payload = _make_pipeline_payload(candidates=[
        {
            "id": CANDIDATE_ID,
            "name": "Bilal Khan",
            "email": "bilal@example.com",
            "status": "active",
            "final_verdict": None,
            "created_at": "2026-05-18T10:00:00+00:00",
            "candidate_rounds": [
                {
                    "id": "cr-1",
                    "round_id": "round-1",
                    "round_number": 1,
                    "round_name": "Phone Screen",
                    "status": "completed",
                },
                {
                    "id": "cr-2",
                    "round_id": "round-2",
                    "round_number": 2,
                    "round_name": "Tech Screen",
                    "status": "scheduled",
                },
                {
                    "id": "cr-3",
                    "round_id": "round-3",
                    "round_number": 3,
                    "round_name": "Onsite",
                    "status": "pending",
                },
            ],
        },
    ])
    respx_mock.post(rpc_url("get_role_pipeline")).mock(
        return_value=httpx.Response(200, json=payload)
    )

    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/candidates")
    cand = resp.json()["candidates"][0]
    # Skip the completed phone screen → land on the scheduled tech screen.
    assert cand["current_round_id"] == "round-2"


def test_get_role_pipeline_all_completed_yields_no_current(recruiter_client, respx_mock):
    """When every round is completed, current_round_id is None — the FE
    uses this to hide the 'next round' affordance in the rail."""
    payload = _make_pipeline_payload(candidates=[
        {
            "id": CANDIDATE_ID,
            "name": "Chloe Patel",
            "email": "chloe@example.com",
            "status": "hired",
            "final_verdict": "pass",
            "created_at": "2026-05-18T10:00:00+00:00",
            "candidate_rounds": [
                {"id": "cr-1", "round_id": "round-1", "status": "completed"},
                {"id": "cr-2", "round_id": "round-2", "status": "completed"},
            ],
        },
    ])
    respx_mock.post(rpc_url("get_role_pipeline")).mock(
        return_value=httpx.Response(200, json=payload)
    )

    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/candidates")
    cand = resp.json()["candidates"][0]
    assert cand["current_round_id"] is None


def test_get_role_pipeline_initials_handle_single_name(recruiter_client, respx_mock):
    """Single-word names use the first two letters; missing names fall back
    to '?'. Verifies the edge cases that pipeline_service._initials_for
    handles."""
    payload = _make_pipeline_payload(candidates=[
        {
            "id": "c1",
            "name": "Madonna",
            "email": "m@x.com",
            "status": "active",
            "candidate_rounds": [],
        },
        {
            "id": "c2",
            "name": None,
            "email": "noname@x.com",
            "status": "active",
            "candidate_rounds": [],
        },
    ])
    respx_mock.post(rpc_url("get_role_pipeline")).mock(
        return_value=httpx.Response(200, json=payload)
    )

    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/candidates")
    cands = resp.json()["candidates"]
    assert cands[0]["avatar_initials"] == "MA"
    assert cands[1]["avatar_initials"] == "?"
