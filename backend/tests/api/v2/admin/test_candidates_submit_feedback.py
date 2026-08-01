"""BE-S4b: admin candidates router — atomic submit_feedback via RPC.

`PUT /admin/candidate-rounds/{cr_id}/feedback` previously did, with NO
transaction, a per-row insert/update loop over `candidate_feedback` — a mid-loop
failure left feedback partially written. It is now a single transactional RPC
(`admin_submit_candidate_feedback`, migration 106). The router calls the RPC and
builds the `SubmitFeedbackResponse` from its returned rows.

These tests pin:
  - success drives the RPC and returns the submitted feedback (same response shape)
  - BAD_QUESTION from the RPC maps to 400 (no partial write)
  - FEEDBACK_NOT_FOUND from the RPC (update target missing) maps to 404
  - a generic RPC failure maps to a non-2xx (no partial write surfaced)
  - 404 when the candidate round does not exist (pre-read short-circuits the RPC)
  - non-staff caller is rejected with 403 before any DB work
"""
import httpx

from app.dependencies import get_current_user, require_staff
from app.main import app
from tests.conftest import RECRUITER_USER
from tests.helpers.supabase_mocks import rest_url, rpc_url
from tests.helpers.mock_data import (
    CANDIDATE_ROUND_ID,
    ROUND_ID,
    FEEDBACK_QUESTION_ID,
    FEEDBACK_ID,
    NOW,
)

V2_ROOT = "/api/v2"


def _pg_error(code: str, message: str, status_code: int = 400):
    return httpx.Response(
        status_code,
        json={"code": code, "message": message, "details": None, "hint": None},
    )


def _cr_pre_read():
    """The router pre-reads the CR (id, round_id) before calling the RPC."""
    return {"id": CANDIDATE_ROUND_ID, "round_id": ROUND_ID}


def _question_row():
    return {
        "id": FEEDBACK_QUESTION_ID,
        "heading": "Problem Solving",
        "question_number": 1,
    }


def _mock_questions(respx_mock):
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[_question_row()])
    )


def _rpc_rows():
    """What admin_submit_candidate_feedback returns: the written rows, in order."""
    return [
        {
            "id": FEEDBACK_ID,
            "feedback_question_id": FEEDBACK_QUESTION_ID,
            "feedback_text": "Solid problem solving",
            "evidence": ["said X"],
            "evidence_status": "supported",
            "source": "manual",
            "created_at": NOW,
            "updated_at": NOW,
        }
    ]


def _payload():
    return {
        "feedback": [
            {
                "feedback_question_id": FEEDBACK_QUESTION_ID,
                "feedback_text": "Solid problem solving",
            }
        ],
        "source": "manual",
    }


def test_submit_feedback_success_calls_rpc(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_pre_read()])
    )
    _mock_questions(respx_mock)
    rpc_route = respx_mock.post(rpc_url("admin_submit_candidate_feedback")).mock(
        return_value=httpx.Response(200, json=_rpc_rows())
    )

    resp = staff_client.put(
        f"{V2_ROOT}/admin/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json=_payload(),
    )

    assert resp.status_code == 200, resp.text
    assert rpc_route.called
    body = resp.json()
    assert body["candidate_round_id"] == CANDIDATE_ROUND_ID
    assert body["total_submitted"] == 1
    assert len(body["feedback"]) == 1
    fb = body["feedback"][0]
    assert fb["id"] == FEEDBACK_ID
    assert fb["feedback_question_id"] == FEEDBACK_QUESTION_ID
    assert fb["heading"] == "Problem Solving"
    assert fb["question_number"] == 1
    assert fb["feedback_text"] == "Solid problem solving"
    assert fb["source"] == "manual"


def test_submit_feedback_bad_question_maps_400(staff_client, respx_mock):
    """RPC raises BAD_QUESTION (tx rolled back) -> 400, nothing written."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_pre_read()])
    )
    _mock_questions(respx_mock)
    respx_mock.post(rpc_url("admin_submit_candidate_feedback")).mock(
        return_value=_pg_error("P0001", "BAD_QUESTION", status_code=400)
    )

    resp = staff_client.put(
        f"{V2_ROOT}/admin/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json=_payload(),
    )
    assert resp.status_code == 400, resp.text


def test_submit_feedback_missing_update_target_maps_404(staff_client, respx_mock):
    """RPC raises FEEDBACK_NOT_FOUND when an update targets a row that does not
    exist for this candidate round -> 404, tx rolled back."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_pre_read()])
    )
    _mock_questions(respx_mock)
    respx_mock.post(rpc_url("admin_submit_candidate_feedback")).mock(
        return_value=_pg_error("P0001", "FEEDBACK_NOT_FOUND", status_code=400)
    )

    payload = _payload()
    payload["feedback"][0]["id"] = FEEDBACK_ID

    resp = staff_client.put(
        f"{V2_ROOT}/admin/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json=payload,
    )
    assert resp.status_code == 404, resp.text


def test_submit_feedback_generic_rpc_failure_maps_error(staff_client, respx_mock):
    """A DB-level failure inside the RPC surfaces as a non-2xx, never a partial
    success."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_pre_read()])
    )
    _mock_questions(respx_mock)
    respx_mock.post(rpc_url("admin_submit_candidate_feedback")).mock(
        return_value=_pg_error("XX000", "internal error", status_code=500)
    )

    resp = staff_client.put(
        f"{V2_ROOT}/admin/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json=_payload(),
    )
    assert resp.status_code >= 400, resp.text
    assert resp.status_code != 200


def test_submit_feedback_404_when_cr_missing(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    rpc_route = respx_mock.post(rpc_url("admin_submit_candidate_feedback")).mock(
        return_value=httpx.Response(200, json=_rpc_rows())
    )

    resp = staff_client.put(
        f"{V2_ROOT}/admin/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json=_payload(),
    )
    assert resp.status_code == 404, resp.text
    # Pre-read 404 must short-circuit before the RPC.
    assert not rpc_route.called


def test_submit_feedback_rejects_non_staff(respx_mock):
    """The staff gate runs before any handler/DB work for this endpoint."""
    app.dependency_overrides[get_current_user] = lambda: RECRUITER_USER
    # Intentionally DO NOT override require_staff so it runs for real.
    from fastapi.testclient import TestClient

    rpc_route = respx_mock.post(rpc_url("admin_submit_candidate_feedback")).mock(
        return_value=httpx.Response(200, json=_rpc_rows())
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.put(
            f"{V2_ROOT}/admin/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
            json=_payload(),
        )

    assert resp.status_code == 403, resp.text
    assert not rpc_route.called
