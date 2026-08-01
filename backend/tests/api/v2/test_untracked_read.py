"""
Tests for GET /api/v2/untracked-interviews.

The role-detail v2 spec doesn't cover untracked interviews — the endpoint
exists so the v2 frontend keeps a single `/api/v2/*` base URL. Read-only
in this PR; mutations remain on the FE mock path (TODO PR11).
"""

from uuid import UUID

import httpx

from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user, CurrentUser
from tests.helpers.mock_data import (
    NOW,
    ORG_ID,
    RECRUITER_USER_ID,
    REQ_ID,
)
from tests.helpers.supabase_mocks import rest_url


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


def test_list_untracked_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.get(f"{V2_ROOT}/untracked-interviews")
    assert resp.status_code == 403


def test_list_untracked_empty_when_no_binding(recruiter_client, respx_mock):
    """If the org has no generic-template binding, the list is empty —
    no further Supabase calls needed."""
    respx_mock.get(rest_url("org_generic_template_bindings")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/untracked-interviews")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"items": [], "page": 1, "page_size": 10, "total": 0}


def test_list_untracked_returns_available_row(recruiter_client, respx_mock):
    """End-to-end happy path: one untracked round, no import row,
    returns one 'available' interview shaped for the FE."""
    generic_req_id = "11111111-2222-3333-4444-555555555555"
    cand_id = "22222222-3333-4444-5555-666666666666"
    cr_id = "33333333-4444-5555-6666-777777777777"
    det_id = "44444444-5555-6666-7777-888888888888"

    respx_mock.get(rest_url("org_generic_template_bindings")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "materialized_requisition_id": generic_req_id,
                "template_key": "GLOBAL_UNTRACKED_INTERVIEW_V1",
            }],
        )
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": cand_id,
                "requisition_id": generic_req_id,
                "name": "Pat Untracked",
                "email": "pat@example.com",
            }],
        )
    )
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": cr_id,
                "candidate_id": cand_id,
                "origin_detection_id": det_id,
                "interviewer_email": "interviewer@example.com",
                "status": "completed",
                "scheduled_at": NOW,
                "recording_url": None,
            }],
        )
    )
    respx_mock.get(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": det_id,
                "event_title": "Loop with Pat",
                "event_start": "2026-06-04T08:00:00+00:00",
                "event_end": "2026-06-04T08:45:00+00:00",
            }],
        )
    )
    respx_mock.get(rest_url("untracked_interview_imports")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = recruiter_client.get(f"{V2_ROOT}/untracked-interviews")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["total"] == 1
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["id"] == cr_id
    assert row["candidate_name"] == "Pat Untracked"
    assert row["candidate_email"] == "pat@example.com"
    assert row["event_title"] == "Loop with Pat"
    assert row["event_duration_minutes"] == 45
    assert row["interviewer_email"] == "interviewer@example.com"
    assert row["status"] == "available"
    assert row["imported_requisition_id"] is None
    assert row["imported_candidate_id"] is None


def test_list_untracked_marks_imported(recruiter_client, respx_mock):
    """When an import row exists for the source round, status flips to
    'imported' and the target req/candidate ids surface."""
    generic_req_id = "11111111-2222-3333-4444-555555555555"
    cand_id = "22222222-3333-4444-5555-666666666666"
    cr_id = "33333333-4444-5555-6666-777777777777"
    det_id = "44444444-5555-6666-7777-888888888888"
    target_cand_id = "55555555-6666-7777-8888-999999999999"

    respx_mock.get(rest_url("org_generic_template_bindings")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "materialized_requisition_id": generic_req_id,
                "template_key": "GLOBAL_UNTRACKED_INTERVIEW_V1",
            }],
        )
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": cand_id,
                "requisition_id": generic_req_id,
                "name": "Pat",
                "email": "pat@example.com",
            }],
        )
    )
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": cr_id,
                "candidate_id": cand_id,
                "origin_detection_id": det_id,
                "interviewer_email": "i@x.com",
                "status": "completed",
                "scheduled_at": NOW,
                "recording_url": None,
            }],
        )
    )
    respx_mock.get(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": det_id,
                "event_title": "Loop",
                "event_start": "2026-06-04T09:00:00+00:00",
                "event_end": "2026-06-04T09:30:00+00:00",
            }],
        )
    )
    respx_mock.get(rest_url("untracked_interview_imports")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "source_generic_candidate_round_id": cr_id,
                "target_requisition_id": REQ_ID,
                "target_candidate_id": target_cand_id,
                # Real DB lifecycle value (import_status_check) — the list maps
                # any non-dismissed import to the FE's "imported".
                "import_status": "copied",
                "created_at": NOW,
            }],
        )
    )

    resp = recruiter_client.get(f"{V2_ROOT}/untracked-interviews")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["status"] == "imported"
    assert row["imported_requisition_id"] == REQ_ID
    assert row["imported_candidate_id"] == target_cand_id
