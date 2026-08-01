"""
Tests for the role-detail v2 shared-plan mutation endpoints (PR 3).

Spec: docs/superpowers/specs/2026-05-18-roles-detail-v2-api-design.md §8.1

Mocks Supabase HTTP via respx (same pattern as test_roles_read.py).
The RPC bodies themselves (add_shared_round, delete_shared_round,
reorder_shared_rounds) are tested via SQL static review only — these tests
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
    ROUND_2_ID,
    FEEDBACK_QUESTION_ID,
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


def _make_round_row(
    *,
    round_id: str = ROUND_ID,
    req_id: str = REQ_ID,
    org_id: str = ORG_ID,
    round_number: int = 1,
    for_candidate_id=None,
    removed_from_plan_at=None,
    deleted_at=None,
):
    return {
        "id": round_id,
        "requisition_id": req_id,
        "round_number": round_number,
        "name": "Technical",
        "category": "coding",
        "duration_minutes": 45,
        "description": "x",
        "skills": [],
        "guidelines": [],
        "for_candidate_id": for_candidate_id,
        "removed_from_plan_at": removed_from_plan_at,
        "deleted_at": deleted_at,
        "created_at": NOW,
        "updated_at": NOW,
        "requisitions": {
            "organization_id": org_id,
            "deleted_at": None,
        },
    }


def _make_question_row(
    *,
    q_id: str = FEEDBACK_QUESTION_ID,
    round_id: str = ROUND_ID,
    req_id: str = REQ_ID,
    org_id: str = ORG_ID,
    question_number: int = 1,
    deleted_at=None,
    round_for_candidate_id=None,
    round_removed_from_plan_at=None,
):
    return {
        "id": q_id,
        "round_id": round_id,
        "question_number": question_number,
        "heading": "Problem Solving",
        "description": "Evaluate problem solving",
        "deleted_at": deleted_at,
        "created_at": NOW,
        "updated_at": NOW,
        "rounds": {
            "id": round_id,
            "for_candidate_id": round_for_candidate_id,
            "removed_from_plan_at": round_removed_from_plan_at,
            "deleted_at": None,
            "requisitions": {
                "organization_id": org_id,
                "deleted_at": None,
            },
        },
    }


def _pg_error(code: str, message: str, status_code: int = 400):
    return httpx.Response(
        status_code,
        json={"code": code, "message": message, "details": None, "hint": None},
    )


# ============================================================================
# Endpoint 1 — POST /roles/{id}/plan/rounds
# ============================================================================


def test_add_round_calls_rpc_with_expected_args(recruiter_client, respx_mock):
    captured = {}

    def _capture(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "id": ROUND_ID,
            "round_number": 1,
            "name": "Technical Screen",
            "category": "coding",
            "duration_minutes": 45,
            "description": None,
            "skills": [],
            "guidelines": [],
            "feedback_questions": [],
        })

    rpc_route = respx_mock.post(rpc_url("add_shared_round")).mock(side_effect=_capture)

    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds",
        json={
            "name": "Technical Screen",
            "category": "coding",
            "duration_minutes": 45,
            "position": 2,
            "feedback_questions": [
                {"heading": "Problem Solving", "description": "x"}
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    assert rpc_route.call_count == 1

    body = captured["body"]
    assert body["p_req_id"] == REQ_ID
    assert body["p_org_id"] == ORG_ID
    assert body["p_name"] == "Technical Screen"
    assert body["p_category"] == "coding"
    assert body["p_position"] == 2
    assert body["p_feedback_questions"] == [
        {"heading": "Problem Solving", "description": "x", "question_number": None}
    ]


def test_add_round_404_when_requisition_not_in_org(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("add_shared_round")).mock(
        return_value=_pg_error("P0002", "NOT_FOUND", status_code=400)
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds",
        json={"name": "x", "category": "coding", "duration_minutes": 45},
    )
    assert resp.status_code == 404


def test_add_round_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(
            f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds",
            json={"name": "x", "category": "coding", "duration_minutes": 45},
        )
    assert resp.status_code == 403


# ============================================================================
# Endpoint 2 — PUT /plan/rounds/{round_id}
# ============================================================================


def test_update_round_200_with_patch(recruiter_client, respx_mock):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[_make_round_row()])
    )
    captured = {}

    def _capture_patch(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=[{
            **_make_round_row(),
            "name": "New Name",
            "duration_minutes": 60,
        }])

    respx_mock.route(method="PATCH", url=rest_url("rounds")).mock(side_effect=_capture_patch)

    resp = recruiter_client.put(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}",
        json={"name": "New Name", "duration_minutes": 60},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "New Name"
    assert body["duration_minutes"] == 60
    # PATCH body must include only the changed fields + updated_at.
    sent = captured["body"]
    assert sent["name"] == "New Name"
    assert sent["duration_minutes"] == 60
    assert "updated_at" in sent
    # Untouched fields must NOT appear in the PATCH.
    assert "category" not in sent
    assert "description" not in sent


def test_update_round_400_when_custom_round(recruiter_client, respx_mock):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[
            _make_round_row(for_candidate_id="00000000-0000-0000-0000-000000000040")
        ])
    )
    resp = recruiter_client.put(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}",
        json={"name": "x"},
    )
    assert resp.status_code == 400


def test_update_round_409_when_removed_from_plan(recruiter_client, respx_mock):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[
            _make_round_row(removed_from_plan_at=NOW)
        ])
    )
    resp = recruiter_client.put(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}",
        json={"name": "x"},
    )
    assert resp.status_code == 409


def test_update_round_404_when_other_org(recruiter_client, respx_mock):
    """Cross-org lookup must 404, not 200/403."""
    other_org = "00000000-0000-0000-0000-000000000099"
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[
            _make_round_row(org_id=other_org)
        ])
    )
    resp = recruiter_client.put(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}",
        json={"name": "x"},
    )
    assert resp.status_code == 404


def test_update_round_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.put(
            f"{V2_ROOT}/plan/rounds/{ROUND_ID}",
            json={"name": "x"},
        )
    assert resp.status_code == 403


# ============================================================================
# Endpoint 3 — DELETE /plan/rounds/{round_id}
# ============================================================================


def test_delete_round_200(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("delete_shared_round")).mock(
        return_value=httpx.Response(200, json={
            "deleted_round_id": ROUND_ID,
            "pending_crs_deleted": 3,
        })
    )
    resp = recruiter_client.delete(f"{V2_ROOT}/plan/rounds/{ROUND_ID}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_round_id"] == ROUND_ID
    assert body["pending_crs_deleted"] == 3


def test_delete_round_409_when_last_round(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("delete_shared_round")).mock(
        return_value=_pg_error("P0001", "LAST_ROUND", status_code=400)
    )
    resp = recruiter_client.delete(f"{V2_ROOT}/plan/rounds/{ROUND_ID}")
    assert resp.status_code == 409
    assert "last shared round" in resp.json()["detail"].lower()


def test_delete_round_400_when_wrong_path_custom_round(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("delete_shared_round")).mock(
        return_value=_pg_error("P0001", "WRONG_PATH", status_code=400)
    )
    resp = recruiter_client.delete(f"{V2_ROOT}/plan/rounds/{ROUND_ID}")
    assert resp.status_code == 400
    assert "candidate-journey" in resp.json()["detail"].lower()


def test_delete_round_idempotent_on_second_call(recruiter_client, respx_mock):
    """A second delete after the round is already removed returns 200 (idempotent)."""
    respx_mock.post(rpc_url("delete_shared_round")).mock(
        return_value=_pg_error("P0001", "ALREADY_REMOVED", status_code=400)
    )
    resp = recruiter_client.delete(f"{V2_ROOT}/plan/rounds/{ROUND_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted_round_id"] == ROUND_ID


def test_delete_round_404_when_not_found(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("delete_shared_round")).mock(
        return_value=_pg_error("P0002", "NOT_FOUND", status_code=400)
    )
    resp = recruiter_client.delete(f"{V2_ROOT}/plan/rounds/{ROUND_ID}")
    assert resp.status_code == 404


def test_delete_round_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.delete(f"{V2_ROOT}/plan/rounds/{ROUND_ID}")
    assert resp.status_code == 403


# ============================================================================
# Endpoint 4 — POST /roles/{id}/plan/rounds/reorder
# ============================================================================


def test_reorder_rounds_428_when_no_if_match(recruiter_client, respx_mock):
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds/reorder",
        json=[
            {"round_id": ROUND_ID, "round_number": 1},
            {"round_id": ROUND_2_ID, "round_number": 2},
        ],
    )
    assert resp.status_code == 428


def test_reorder_rounds_412_when_if_match_stale(recruiter_client, respx_mock):
    # Requisition exists for org.
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[{"id": REQ_ID}])
    )
    # Current DB max(updated_at) is *newer* than client's If-Match.
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[
            {"id": ROUND_ID, "updated_at": "2025-01-15T12:00:00+00:00"}
        ])
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds/reorder",
        headers={"If-Match": "2025-01-15T10:00:00+00:00"},
        json=[
            {"round_id": ROUND_ID, "round_number": 1},
            {"round_id": ROUND_2_ID, "round_number": 2},
        ],
    )
    assert resp.status_code == 412


def test_reorder_rounds_200_with_etag(recruiter_client, respx_mock):
    new_max_ts = "2025-01-15T13:00:00+00:00"

    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[{"id": REQ_ID}])
    )
    # DB max(updated_at) matches client's If-Match (fresh).
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[
            {"id": ROUND_ID, "updated_at": "2025-01-15T10:00:00+00:00"}
        ])
    )
    respx_mock.post(rpc_url("reorder_shared_rounds")).mock(
        return_value=httpx.Response(200, json={
            "rounds": [
                {"id": ROUND_ID, "round_number": 1, "updated_at": new_max_ts},
                {"id": ROUND_2_ID, "round_number": 2, "updated_at": new_max_ts},
            ],
            "etag": new_max_ts,
        })
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds/reorder",
        headers={"If-Match": "2025-01-15T10:00:00+00:00"},
        json=[
            {"round_id": ROUND_ID, "round_number": 1},
            {"round_id": ROUND_2_ID, "round_number": 2},
        ],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["etag"] == new_max_ts
    assert body["rounds"][0]["round_number"] == 1
    assert body["rounds"][1]["round_number"] == 2


def test_reorder_rounds_404_when_role_in_other_org(recruiter_client, respx_mock):
    # Requisition not in user's org -> empty result.
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds/reorder",
        headers={"If-Match": "2025-01-15T10:00:00+00:00"},
        json=[{"round_id": ROUND_ID, "round_number": 1}],
    )
    assert resp.status_code == 404


def test_reorder_rounds_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(
            f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds/reorder",
            headers={"If-Match": "2025-01-15T10:00:00+00:00"},
            json=[{"round_id": ROUND_ID, "round_number": 1}],
        )
    assert resp.status_code == 403


# ============================================================================
# Endpoint 5 — POST /plan/rounds/{round_id}/questions
# ============================================================================


def test_add_question_201_with_explicit_number(recruiter_client, respx_mock):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[_make_round_row()])
    )
    captured = {}

    def _capture_insert(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(201, json=[{
            "id": FEEDBACK_QUESTION_ID,
            "round_id": ROUND_ID,
            "question_number": 3,
            "heading": "New Q",
            "description": "desc",
        }])

    respx_mock.post(rest_url("feedback_questions")).mock(side_effect=_capture_insert)

    resp = recruiter_client.post(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}/questions",
        json={"heading": "New Q", "description": "desc", "question_number": 3},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["heading"] == "New Q"
    assert body["question_number"] == 3
    assert captured["body"]["question_number"] == 3


def test_add_question_defaults_question_number(recruiter_client, respx_mock):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[_make_round_row()])
    )
    # MAX(question_number) lookup returns 2 -> next is 3.
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[{"question_number": 2}])
    )
    captured = {}

    def _capture_insert(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(201, json=[{
            "id": FEEDBACK_QUESTION_ID,
            "round_id": ROUND_ID,
            "question_number": 3,
            "heading": "New Q",
            "description": None,
        }])

    respx_mock.post(rest_url("feedback_questions")).mock(side_effect=_capture_insert)

    resp = recruiter_client.post(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}/questions",
        json={"heading": "New Q"},
    )
    assert resp.status_code == 201, resp.text
    assert captured["body"]["question_number"] == 3


def test_add_question_400_when_custom_round(recruiter_client, respx_mock):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[
            _make_round_row(for_candidate_id="00000000-0000-0000-0000-000000000040")
        ])
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}/questions",
        json={"heading": "x"},
    )
    assert resp.status_code == 400


def test_add_question_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(
            f"{V2_ROOT}/plan/rounds/{ROUND_ID}/questions",
            json={"heading": "x"},
        )
    assert resp.status_code == 403


def test_add_question_404_when_round_in_other_org(recruiter_client, respx_mock):
    other_org = "00000000-0000-0000-0000-000000000099"
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[_make_round_row(org_id=other_org)])
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}/questions",
        json={"heading": "x"},
    )
    assert resp.status_code == 404


# ============================================================================
# Endpoint 6 — PUT /plan/questions/{question_id}
# ============================================================================


def test_update_question_200(recruiter_client, respx_mock):
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[_make_question_row()])
    )
    respx_mock.route(method="PATCH", url=rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[{
            "id": FEEDBACK_QUESTION_ID,
            "round_id": ROUND_ID,
            "question_number": 1,
            "heading": "Updated Heading",
            "description": "Updated desc",
        }])
    )
    resp = recruiter_client.put(
        f"{V2_ROOT}/plan/questions/{FEEDBACK_QUESTION_ID}",
        json={"heading": "Updated Heading", "description": "Updated desc"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["heading"] == "Updated Heading"


def test_update_question_404_when_other_org(recruiter_client, respx_mock):
    other_org = "00000000-0000-0000-0000-000000000099"
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[
            _make_question_row(org_id=other_org)
        ])
    )
    resp = recruiter_client.put(
        f"{V2_ROOT}/plan/questions/{FEEDBACK_QUESTION_ID}",
        json={"heading": "x"},
    )
    assert resp.status_code == 404


def test_update_question_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.put(
            f"{V2_ROOT}/plan/questions/{FEEDBACK_QUESTION_ID}",
            json={"heading": "x"},
        )
    assert resp.status_code == 403


# ============================================================================
# Endpoint 7 — DELETE /plan/questions/{question_id}
# ============================================================================


def test_delete_question_200(recruiter_client, respx_mock):
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[_make_question_row()])
    )
    captured = {}

    def _capture_patch(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=[{
            "id": FEEDBACK_QUESTION_ID,
            "deleted_at": NOW,
        }])

    respx_mock.route(method="PATCH", url=rest_url("feedback_questions")).mock(
        side_effect=_capture_patch
    )

    resp = recruiter_client.delete(
        f"{V2_ROOT}/plan/questions/{FEEDBACK_QUESTION_ID}"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted_question_id"] == FEEDBACK_QUESTION_ID
    # Soft delete: deleted_at must be set, not a hard DELETE call.
    assert "deleted_at" in captured["body"]


def test_delete_question_404_when_other_org(recruiter_client, respx_mock):
    other_org = "00000000-0000-0000-0000-000000000099"
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[
            _make_question_row(org_id=other_org)
        ])
    )
    resp = recruiter_client.delete(
        f"{V2_ROOT}/plan/questions/{FEEDBACK_QUESTION_ID}"
    )
    assert resp.status_code == 404


def test_delete_question_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.delete(
            f"{V2_ROOT}/plan/questions/{FEEDBACK_QUESTION_ID}"
        )
    assert resp.status_code == 403
