"""
Tests for the role-detail v2 candidate/journey mutation endpoints (PR 4a).

Spec: docs/superpowers/specs/2026-05-18-roles-detail-v2-api-design.md §8.2

Mocks Supabase HTTP via respx (same pattern as test_roles_mutations.py).
The RPC bodies themselves (add_candidate_with_backfill, add_custom_round,
delete_candidate_round) are tested via SQL static review only — these tests
verify the Python handlers map inputs/outputs/errors correctly.
"""

import json
import httpx
import pytest
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user, CurrentUser
from tests.helpers.mock_data import (
    ORG_ID,
    REQ_ID,
    ROUND_ID,
    CANDIDATE_ID,
    CANDIDATE_ROUND_ID,
    RECRUITER_USER_ID,
    NOW,
)
from tests.helpers.supabase_mocks import rest_url, rpc_url


V2_ROOT = "/api/v2"


def _no_org_client():
    no_org_user = CurrentUser(
        id=UUID(RECRUITER_USER_ID),
        email="recruiter@test.com",
        is_staff=False,
        organization_id=None,
    )
    app.dependency_overrides[get_current_user] = lambda: no_org_user
    return TestClient(app, raise_server_exceptions=False)


def _pg_error(code: str, message: str, status_code: int = 400):
    return httpx.Response(
        status_code,
        json={"code": code, "message": message, "details": None, "hint": None},
    )


def _make_requisition_row(status: str = "planned", org_id: str = ORG_ID):
    return {
        "id": REQ_ID,
        "organization_id": org_id,
        "role_title": "Software Engineer",
        "role_location": "Remote",
        "status": status,
        "created_by": RECRUITER_USER_ID,
        "experience_min_years": 3,
        "experience_max_years": 5,
        "must_have_skills": [],
        "good_to_have_skills": [],
        "intake_notes": None,
        "job_description": None,
        "created_at": NOW,
        "updated_at": NOW,
        "deleted_at": None,
    }


# ============================================================================
# Endpoint 1 — POST /roles/{role_id}/candidates
# ============================================================================


def test_add_candidate_201_with_backfill(recruiter_client, respx_mock):
    captured = {}

    def _capture(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "candidate": {
                "id": CANDIDATE_ID,
                "requisition_id": REQ_ID,
                "name": "Alice",
                "email": "alice@example.com",
                "phone": None,
                "resume_url": None,
                "status": "active",
                "final_verdict": None,
                "created_at": NOW,
                "updated_at": NOW,
                "deleted_at": None,
            },
            "counts": {
                "candidates_total": 1,
                "candidates_active": 1,
                "candidates_hired": 0,
                "candidates_rejected": 0,
                "rounds_total": 3,
            },
        })

    rpc_route = respx_mock.post(rpc_url("add_candidate_with_backfill")).mock(
        side_effect=_capture
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates",
        json={
            "name": "Alice",
            "email": "alice@example.com",
            "source": "linkedin",  # accepted but silently dropped (spec §15)
        },
    )
    assert resp.status_code == 201, resp.text
    assert rpc_route.call_count == 1

    body = captured["body"]
    assert body["p_req_id"] == REQ_ID
    assert body["p_org_id"] == ORG_ID
    assert body["p_name"] == "Alice"
    assert body["p_email"] == "alice@example.com"
    assert body["p_phone"] is None
    assert body["p_resume_url"] is None
    # `source` must NOT be forwarded — no DB column exists.
    assert "p_source" not in body
    assert "source" not in body

    resp_body = resp.json()
    assert resp_body["candidate"]["name"] == "Alice"
    assert resp_body["counts"]["candidates_active"] == 1


def test_add_candidate_404_when_req_not_in_org(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("add_candidate_with_backfill")).mock(
        return_value=_pg_error("P0002", "NOT_FOUND")
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates",
        json={"name": "Alice", "email": "alice@example.com"},
    )
    assert resp.status_code == 404


def test_add_candidate_409_when_req_closed(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("add_candidate_with_backfill")).mock(
        return_value=_pg_error("P0001", "REQ_CLOSED")
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates",
        json={"name": "Alice", "email": "alice@example.com"},
    )
    assert resp.status_code == 409
    assert "closed" in resp.json()["detail"].lower()


def test_add_candidate_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(
            f"{V2_ROOT}/roles/{REQ_ID}/candidates",
            json={"name": "Alice", "email": "alice@example.com"},
        )
    assert resp.status_code == 403


# ============================================================================
# Endpoint 2 — POST /roles/{role_id}/candidates/{candidate_id}/rounds
# ============================================================================


def test_add_custom_round_201(recruiter_client, respx_mock):
    captured = {}

    def _capture(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "round": {
                "id": ROUND_ID,
                "round_number": 1,
                "name": "Founder chat",
                "category": "behavioural",
                "duration_minutes": 30,
                "description": None,
                "skills": [],
                "guidelines": [],
                "is_custom": True,
                "for_candidate_id": CANDIDATE_ID,
                "feedback_questions": [],
            },
            "candidate_round": {
                "id": CANDIDATE_ROUND_ID,
                "candidate_id": CANDIDATE_ID,
                "round_id": ROUND_ID,
                "status": "pending",
                "scheduled_at": None,
                "completed_at": None,
                "created_at": NOW,
                "updated_at": NOW,
            },
        })

    rpc_route = respx_mock.post(rpc_url("add_custom_round")).mock(side_effect=_capture)

    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/rounds",
        json={
            "name": "Founder chat",
            "category": "behavioural",
            "duration_minutes": 30,
        },
    )
    assert resp.status_code == 201, resp.text
    assert rpc_route.call_count == 1

    body = captured["body"]
    assert body["p_req_id"] == REQ_ID
    assert body["p_candidate_id"] == CANDIDATE_ID
    assert body["p_org_id"] == ORG_ID
    assert body["p_name"] == "Founder chat"
    assert body["p_duration_minutes"] == 30

    resp_body = resp.json()
    assert resp_body["round"]["is_custom"] is True
    assert resp_body["candidate_round"]["status"] == "pending"


def test_add_custom_round_409_when_candidate_inactive(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("add_custom_round")).mock(
        return_value=_pg_error("P0001", "CANDIDATE_INACTIVE")
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/rounds",
        json={"name": "Founder chat", "category": "behavioural"},
    )
    assert resp.status_code == 409
    assert "hired" in resp.json()["detail"].lower() or "rejected" in resp.json()["detail"].lower()


def test_add_custom_round_409_when_req_closed(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("add_custom_round")).mock(
        return_value=_pg_error("P0001", "REQ_CLOSED")
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/rounds",
        json={"name": "Founder chat", "category": "behavioural"},
    )
    assert resp.status_code == 409
    assert "closed" in resp.json()["detail"].lower()


def test_add_custom_round_404_when_req_or_candidate_missing(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("add_custom_round")).mock(
        return_value=_pg_error("P0002", "NOT_FOUND")
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/rounds",
        json={"name": "Founder chat", "category": "behavioural"},
    )
    assert resp.status_code == 404


def test_add_custom_round_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(
            f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/rounds",
            json={"name": "x", "category": "behavioural"},
        )
    assert resp.status_code == 403


# ============================================================================
# Endpoint 3 — DELETE /roles/{role_id}/candidates/{cid}/rounds/{cr_id}
# ============================================================================


def test_delete_candidate_round_200_when_pending(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("delete_candidate_round")).mock(
        return_value=httpx.Response(200, json={
            "deleted_cr_id": CANDIDATE_ROUND_ID,
            "deleted_round_id": None,
        })
    )
    resp = recruiter_client.delete(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/rounds/{CANDIDATE_ROUND_ID}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_cr_id"] == CANDIDATE_ROUND_ID
    assert body["deleted_round_id"] is None


def test_delete_candidate_round_200_custom_round_also_deletes_round(
    recruiter_client, respx_mock
):
    respx_mock.post(rpc_url("delete_candidate_round")).mock(
        return_value=httpx.Response(200, json={
            "deleted_cr_id": CANDIDATE_ROUND_ID,
            "deleted_round_id": ROUND_ID,
        })
    )
    resp = recruiter_client.delete(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/rounds/{CANDIDATE_ROUND_ID}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_cr_id"] == CANDIDATE_ROUND_ID
    assert body["deleted_round_id"] == ROUND_ID


def test_delete_candidate_round_409_when_scheduled(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("delete_candidate_round")).mock(
        return_value=_pg_error("P0001", "NOT_PENDING")
    )
    resp = recruiter_client.delete(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/rounds/{CANDIDATE_ROUND_ID}"
    )
    assert resp.status_code == 409
    assert "scheduled" in resp.json()["detail"].lower()


def test_delete_candidate_round_409_when_completed(recruiter_client, respx_mock):
    # Backend collapses every non-pending status into NOT_PENDING.
    respx_mock.post(rpc_url("delete_candidate_round")).mock(
        return_value=_pg_error("P0001", "NOT_PENDING")
    )
    resp = recruiter_client.delete(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/rounds/{CANDIDATE_ROUND_ID}"
    )
    assert resp.status_code == 409


def test_delete_candidate_round_404_when_not_found(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("delete_candidate_round")).mock(
        return_value=_pg_error("P0002", "NOT_FOUND")
    )
    resp = recruiter_client.delete(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/rounds/{CANDIDATE_ROUND_ID}"
    )
    assert resp.status_code == 404


def test_delete_candidate_round_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.delete(
            f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/rounds/{CANDIDATE_ROUND_ID}"
        )
    assert resp.status_code == 403


# ============================================================================
# Endpoint 4 — POST /roles/{role_id}/close
# ============================================================================


def test_close_role_200(recruiter_client, respx_mock):
    captured = {}

    def _capture(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=[
            {**_make_requisition_row(status="closed")}
        ])

    respx_mock.route(method="PATCH", url=rest_url("requisitions")).mock(
        side_effect=_capture
    )

    resp = recruiter_client.post(f"{V2_ROOT}/roles/{REQ_ID}/close")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "closed"
    sent = captured["body"]
    assert sent["status"] == "closed"
    assert "updated_at" in sent


def test_close_role_idempotent_when_already_closed(recruiter_client, respx_mock):
    # The PATCH no-ops (status already closed) — returns [].
    respx_mock.route(method="PATCH", url=rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    # Disambiguation SELECT returns the current (already-closed) row.
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[_make_requisition_row(status="closed")])
    )

    resp = recruiter_client.post(f"{V2_ROOT}/roles/{REQ_ID}/close")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "closed"


def test_close_role_404_when_not_in_org(recruiter_client, respx_mock):
    respx_mock.route(method="PATCH", url=rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.post(f"{V2_ROOT}/roles/{REQ_ID}/close")
    assert resp.status_code == 404


def test_close_role_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(f"{V2_ROOT}/roles/{REQ_ID}/close")
    assert resp.status_code == 403


# ============================================================================
# Endpoint 5 — POST /roles/{role_id}/reopen
# ============================================================================


def test_reopen_role_200(recruiter_client, respx_mock):
    captured = {}

    def _capture(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=[_make_requisition_row(status="planned")])

    respx_mock.route(method="PATCH", url=rest_url("requisitions")).mock(
        side_effect=_capture
    )

    resp = recruiter_client.post(f"{V2_ROOT}/roles/{REQ_ID}/reopen")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "planned"
    sent = captured["body"]
    assert sent["status"] == "planned"


def test_reopen_role_idempotent_when_already_open(recruiter_client, respx_mock):
    # PATCH matches no rows (status != 'closed') — returns [].
    respx_mock.route(method="PATCH", url=rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[_make_requisition_row(status="planned")])
    )

    resp = recruiter_client.post(f"{V2_ROOT}/roles/{REQ_ID}/reopen")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "planned"


def test_reopen_role_404_when_not_in_org(recruiter_client, respx_mock):
    respx_mock.route(method="PATCH", url=rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.post(f"{V2_ROOT}/roles/{REQ_ID}/reopen")
    assert resp.status_code == 404


def test_reopen_role_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(f"{V2_ROOT}/roles/{REQ_ID}/reopen")
    assert resp.status_code == 403
