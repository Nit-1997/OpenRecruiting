"""Tests for the v2 debrief router (spec §9.1) + the `debrief` intent.

Auth comes from the conftest `recruiter_client` / `unauthed_client` fixtures.
Supabase is mocked via respx (rest_url / rpc_url). The Cortex skill HTTP call is
mocked by patching CortexDebriefClient.generate so no network fires. The intent
test replaces the gateway client with llm-core's FakeLLM via
app.dependency_overrides (mirrors test_assistant_route_api.py).
"""
from __future__ import annotations

import httpx
import pytest

import app.api.v2.routers.debrief as debrief_router
from app.dependencies import get_llm_client
from app.main import app
from tests.helpers.mock_data import ORG_ID, REQ_ID, RECRUITER_USER_ID
from tests.helpers.supabase_mocks import rest_url, rpc_url

V2_ROOT = "/api/v2"

CAND_A = "00000000-0000-0000-0000-0000000000a1"
CAND_B = "00000000-0000-0000-0000-0000000000a2"
PACKET_ID = "00000000-0000-0000-0000-0000000000f1"


def _candidate_row(cid, *, completed=True, feedback=True, rated=True, org=ORG_ID, req=REQ_ID, name="C"):
    """A candidate row with its nested candidate_rounds -> candidate_feedback embed.
    `ready` now requires a completed round carrying a `rating` (spec 2026-06-08 §5)."""
    fb = [{"evidence_status": "verified"}] if (completed and feedback) else []
    rounds = [{
        "processing_status": "completed" if completed else "none",
        "status": "completed",
        "rating": "yes" if (completed and rated) else None,
        "candidate_feedback": fb,
    }]
    return {
        "id": cid, "name": name, "requisition_id": req,
        "requisitions": {"id": req, "role_title": "PM", "organization_id": org, "deleted_at": None},
        "candidate_rounds": rounds,
    }


def _full_packet(**over):
    base = {
        "id": PACKET_ID, "requisition_id": REQ_ID, "role_title": "PM",
        "title": "PM Debrief", "subtitle": "2 finalists",
        "generated_at": "2026-06-07T10:00:00Z", "generated_by": "Scout debrief agent",
        "status": "fresh", "confidence": "high", "verdict": "hire",
        "headline_recommendation": "Hire Ada.",
        "panel_members": [], "candidates": [], "source_stats": {"scorecards": 2, "transcripts": 1},
        "themes": [], "decision_matrix": [], "risks": [], "next_steps": [],
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_roles_requires_auth(unauthed_client):
    resp = unauthed_client.get(f"{V2_ROOT}/debrief/roles")
    assert resp.status_code in (401, 403)


def test_generate_requires_auth(unauthed_client):
    resp = unauthed_client.post(
        f"{V2_ROOT}/debrief/generate",
        json={"requisition_id": REQ_ID, "candidate_ids": [CAND_A, CAND_B]},
    )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Pickers — eligibility filtering
# ---------------------------------------------------------------------------
def test_roles_lists_only_two_plus_ready(recruiter_client, respx_mock):
    rows = [_candidate_row(CAND_A), _candidate_row(CAND_B)]
    respx_mock.get(rest_url("candidates")).mock(return_value=httpx.Response(200, json=rows))
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/roles")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["requisition_id"] == REQ_ID
    assert body[0]["eligible_candidate_count"] == 2


def test_roles_drops_role_with_single_ready(recruiter_client, respx_mock):
    rows = [_candidate_row(CAND_A), _candidate_row(CAND_B, completed=False)]
    respx_mock.get(rest_url("candidates")).mock(return_value=httpx.Response(200, json=rows))
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/roles")
    assert resp.status_code == 200
    assert resp.json() == []


def test_candidates_tagged_with_eligibility(recruiter_client, respx_mock):
    rows = [_candidate_row(CAND_A), _candidate_row(CAND_B, completed=False)]
    respx_mock.get(rest_url("candidates")).mock(return_value=httpx.Response(200, json=rows))
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/roles/{REQ_ID}/candidates")
    assert resp.status_code == 200
    by_id = {c["candidate_id"]: c for c in resp.json()}
    assert by_id[CAND_A]["eligibility"] == "ready"
    assert by_id[CAND_A]["signal"]["feedback_count"] == 1
    assert by_id[CAND_A]["signal"]["evidence_backed_count"] == 1
    assert by_id[CAND_B]["eligibility"] == "awaiting_signal"


def test_candidates_completed_unrated_is_awaiting_signal(recruiter_client, respx_mock):
    """A completed round with NO rating → awaiting_signal, NOT ready: it can't be
    scored (spec 2026-06-08 §5). Feedback presence no longer drives readiness."""
    rows = [_candidate_row(CAND_A, completed=True, feedback=False, rated=False)]
    respx_mock.get(rest_url("candidates")).mock(return_value=httpx.Response(200, json=rows))
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/roles/{REQ_ID}/candidates")
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["eligibility"] == "awaiting_signal"
    assert item["rated_round_count"] == 0


# ---------------------------------------------------------------------------
# Generate — validation + happy path
# ---------------------------------------------------------------------------
def test_generate_rejects_under_two_candidates(recruiter_client):
    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/generate",
        json={"requisition_id": REQ_ID, "candidate_ids": [CAND_A]},
    )
    assert resp.status_code == 422


def test_generate_rejects_over_five_candidates(recruiter_client):
    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/generate",
        json={"requisition_id": REQ_ID, "candidate_ids": [f"c{i}" for i in range(6)]},
    )
    assert resp.status_code == 422


def test_generate_happy_path_returns_draft(recruiter_client, respx_mock, monkeypatch):
    # eligibility read: both candidates ready
    rows = [_candidate_row(CAND_A), _candidate_row(CAND_B)]
    respx_mock.get(rest_url("candidates")).mock(return_value=httpx.Response(200, json=rows))
    # insert_generating (POST) -> returns the new row id; finalize_draft (PATCH) -> 200
    respx_mock.post(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(201, json=[{"id": PACKET_ID}])
    )
    respx_mock.patch(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[{"id": PACKET_ID}])
    )

    async def _fake_generate(self, *, org_id, requisition_id, candidate_ids):
        return _full_packet()

    monkeypatch.setattr(debrief_router.CortexDebriefClient, "generate", _fake_generate)

    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/generate",
        json={"requisition_id": REQ_ID, "candidate_ids": [CAND_A, CAND_B]},
    )
    assert resp.status_code == 200
    # generate now lands a DRAFT (no supersede) — the FE saves it explicitly.
    assert resp.json() == {"packet_id": PACKET_ID, "status": "draft"}


def test_generate_rejects_foreign_candidate(recruiter_client, respx_mock):
    # Only CAND_A is on the role; the request also includes an unknown candidate.
    rows = [_candidate_row(CAND_A)]
    respx_mock.get(rest_url("candidates")).mock(return_value=httpx.Response(200, json=rows))
    respx_mock.post(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(201, json=[{"id": PACKET_ID}])
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/generate",
        json={"requisition_id": REQ_ID, "candidate_ids": [CAND_A, CAND_B]},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Poll + list
# ---------------------------------------------------------------------------
def test_get_packet_returns_body_when_fresh(recruiter_client, respx_mock):
    row = {
        "id": PACKET_ID, "organization_id": ORG_ID, "requisition_id": REQ_ID,
        "status": "fresh", "packet": _full_packet(),
    }
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[row])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/packets/{PACKET_ID}")
    assert resp.status_code == 200
    assert resp.json()["verdict"] == "hire"


def test_get_packet_overlays_superseded_status_onto_body(recruiter_client, respx_mock):
    """FIX 4: the packet JSONB hardcodes status='fresh'; supersede flips only the
    row COLUMN. get_packet must overlay the authoritative row status onto the body
    so a superseded packet renders the 'Superseded' badge (status='superseded')."""
    row = {
        "id": PACKET_ID, "organization_id": ORG_ID, "requisition_id": REQ_ID,
        "status": "superseded",  # authoritative row column
        "packet": _full_packet(status="fresh"),  # stale hardcoded body status
    }
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[row])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/packets/{PACKET_ID}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "superseded"


def test_get_packet_keeps_fresh_status_when_row_is_fresh(recruiter_client, respx_mock):
    """FIX 4: a `fresh` row keeps body status 'fresh' (no spurious flip)."""
    row = {
        "id": PACKET_ID, "organization_id": ORG_ID, "requisition_id": REQ_ID,
        "status": "fresh", "packet": _full_packet(status="fresh"),
    }
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[row])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/packets/{PACKET_ID}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "fresh"


def test_get_packet_returns_body_when_draft(recruiter_client, respx_mock):
    """DRAFT-PREVIEW: generate now lands a `draft` row WITH a packet body. The FE
    polls/previews via GET before committing via /save. The router overlays the
    row status ('draft') onto the body — `draft` MUST be body-valid (200), not a
    ValidationError->500 (which would kill the generate->preview->Save loop)."""
    row = {
        "id": PACKET_ID, "organization_id": ORG_ID, "requisition_id": REQ_ID,
        "status": "draft", "packet": _full_packet(status="fresh"),
    }
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[row])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/packets/{PACKET_ID}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"


def test_get_packet_404_when_generating(recruiter_client, respx_mock):
    row = {
        "id": PACKET_ID, "organization_id": ORG_ID, "requisition_id": REQ_ID,
        "status": "generating", "packet": None,
    }
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[row])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/packets/{PACKET_ID}")
    assert resp.status_code == 404


def test_list_packets_newest_first(recruiter_client, respx_mock):
    rows = [
        {"id": PACKET_ID, "status": "fresh", "candidate_ids": [CAND_A, CAND_B],
         "packet": _full_packet(), "generated_at": "2026-06-07T10:00:00Z",
         "created_at": "2026-06-07T10:00:00Z"},
        {"id": "p2", "status": "superseded", "candidate_ids": [CAND_A],
         "packet": None, "generated_at": None, "created_at": "2026-06-06T10:00:00Z"},
    ]
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=rows)
    )
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/roles/{REQ_ID}/packets")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["packet_id"] == PACKET_ID
    assert body[0]["verdict"] == "hire"
    assert body[1]["verdict"] is None


# ---------------------------------------------------------------------------
# Save — commit draft -> fresh
# ---------------------------------------------------------------------------
def test_save_requires_auth(unauthed_client):
    resp = unauthed_client.post(f"{V2_ROOT}/debrief/packets/{PACKET_ID}/save")
    assert resp.status_code in (401, 403)


def test_save_commits_draft_to_fresh(recruiter_client, respx_mock):
    # get_packet (org-scoped read) -> a draft row
    row = {
        "id": PACKET_ID, "organization_id": ORG_ID, "requisition_id": REQ_ID,
        "status": "draft", "candidate_ids": [CAND_A, CAND_B], "packet": _full_packet(),
    }
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[row])
    )
    # debrief_commit_draft RPC: RETURNS VOID -> PostgREST replies 204 No Content.
    respx_mock.post(rpc_url("debrief_commit_draft")).mock(
        return_value=httpx.Response(204)
    )
    resp = recruiter_client.post(f"{V2_ROOT}/debrief/packets/{PACKET_ID}/save")
    assert resp.status_code == 200
    assert resp.json() == {"packet_id": PACKET_ID, "status": "fresh"}


def test_save_idempotent_when_already_fresh(recruiter_client, respx_mock):
    row = {
        "id": PACKET_ID, "organization_id": ORG_ID, "requisition_id": REQ_ID,
        "status": "fresh", "candidate_ids": [CAND_A, CAND_B], "packet": _full_packet(),
    }
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[row])
    )
    resp = recruiter_client.post(f"{V2_ROOT}/debrief/packets/{PACKET_ID}/save")
    assert resp.status_code == 200
    assert resp.json() == {"packet_id": PACKET_ID, "status": "fresh"}


def test_save_404_when_missing(recruiter_client, respx_mock):
    # single() with no rows -> get_packet returns None -> NotFoundError -> 404
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.post(f"{V2_ROOT}/debrief/packets/{PACKET_ID}/save")
    assert resp.status_code == 404


def test_save_409_when_generating(recruiter_client, respx_mock):
    row = {
        "id": PACKET_ID, "organization_id": ORG_ID, "requisition_id": REQ_ID,
        "status": "generating", "candidate_ids": [CAND_A, CAND_B], "packet": None,
    }
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[row])
    )
    resp = recruiter_client.post(f"{V2_ROOT}/debrief/packets/{PACKET_ID}/save")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------
def test_intent_classifies_debrief(recruiter_client, fake_llm):
    fake_llm.queue_tool_call("emit_route", {"intent": "debrief"})
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    resp = recruiter_client.post(
        f"{V2_ROOT}/assistant/route", json={"text": "debrief the PM finalists"}
    )
    assert resp.status_code == 200
    assert resp.json()["intent"] == "debrief"
