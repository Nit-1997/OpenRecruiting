"""BE-S4: admin candidates router — atomic structured-feedback upsert via RPC.

`PUT /admin/candidate-rounds/{cr_id}/structured-feedback` previously did a
round-level update, a per-row delete loop, and a per-row insert/update loop as
separate awaited statements with no transaction — a mid-loop failure left
feedback half-written. It is now a single transactional RPC
(`admin_set_structured_feedback`, migration 105). The router calls the RPC and
builds the response from its returned envelope.

These tests pin:
  - success drives the RPC and returns the round detail
  - BAD_QUESTION from the RPC maps to 400 (no partial write)
  - a generic RPC failure maps to an error status (no partial write)
  - 404 when the candidate round does not exist
"""
import httpx

from tests.helpers.supabase_mocks import rest_url, rpc_url
from tests.helpers.mock_data import (
    CANDIDATE_ROUND_ID,
    CANDIDATE_ID,
    ROUND_ID,
    FEEDBACK_QUESTION_ID,
    NOW,
)

V2_ROOT = "/api/v2"


def _pg_error(code: str, message: str, status_code: int = 400):
    return httpx.Response(
        status_code,
        json={"code": code, "message": message, "details": None, "hint": None},
    )


def _cr_pre_read():
    """The router pre-reads the CR (existence) before calling the RPC."""
    return {
        "id": CANDIDATE_ROUND_ID,
        "candidate_id": CANDIDATE_ID,
        "round_id": ROUND_ID,
        "status": "completed",
        "summary": None,
        "rating": None,
        "scheduled_at": None,
        "completed_at": NOW,
        "outcome": None,
        "outcome_notes": None,
        "bot_session_id": None,
        "transcript_url": None,
        "recording_url": None,
        "meeting_url": None,
        "created_at": NOW,
        "updated_at": NOW,
        "rounds": {
            "id": ROUND_ID,
            "name": "Technical",
            "round_number": 1,
            "category": "coding",
            "duration_minutes": 45,
            "description": "Tech round",
        },
    }


def _rpc_envelope(summary="Great", rating="strong_yes"):
    """What admin_set_structured_feedback returns: updated CR + ordered entries."""
    cr = _cr_pre_read()
    cr["summary"] = summary
    cr["rating"] = rating
    return {
        "candidate_round": cr,
        "entries": [
            {
                "id": "00000000-0000-0000-0000-0000000000e1",
                "candidate_round_id": CANDIDATE_ROUND_ID,
                "feedback_question_id": FEEDBACK_QUESTION_ID,
                "feedback_text": "Solid problem solving",
                "evidence": ["said X"],
                "evidence_status": "supported",
                "source": "manual",
                "created_at": NOW,
                "updated_at": NOW,
                "feedback_questions": {
                    "heading": "Problem Solving",
                    "question_number": 1,
                    "description": "Eval",
                },
            }
        ],
    }


def _question_row():
    return {
        "id": FEEDBACK_QUESTION_ID,
        "heading": "Problem Solving",
        "question_number": 1,
        "description": "Eval",
    }


def _mock_questions(respx_mock):
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[_question_row()])
    )


def _payload():
    return {
        "feedback": [
            {
                "feedback_question_id": FEEDBACK_QUESTION_ID,
                "feedback_data": "Solid problem solving",
                "evidence": ["said X"],
                "evidence_status": "supported",
            }
        ],
        "round_summary": "Great",
        "round_rating": "strong_yes",
        "source": "manual",
    }


def test_structured_feedback_success_calls_rpc(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_pre_read()])
    )
    _mock_questions(respx_mock)
    rpc_route = respx_mock.post(rpc_url("admin_set_structured_feedback")).mock(
        return_value=httpx.Response(200, json=_rpc_envelope())
    )

    resp = staff_client.put(
        f"{V2_ROOT}/admin/candidate-rounds/{CANDIDATE_ROUND_ID}/structured-feedback",
        json=_payload(),
    )

    assert resp.status_code == 200, resp.text
    assert rpc_route.called
    body = resp.json()
    assert body["summary"] == "Great"
    assert body["rating"] == "strong_yes"
    assert len(body["feedback_questions"]) == 1
    q = body["feedback_questions"][0]
    assert q["heading"] == "Problem Solving"
    assert q["feedback"][0]["feedback_data"] == "Solid problem solving"


def test_structured_feedback_bad_question_maps_400(staff_client, respx_mock):
    """RPC raises BAD_QUESTION (tx rolled back) -> 400, nothing written."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_pre_read()])
    )
    _mock_questions(respx_mock)
    respx_mock.post(rpc_url("admin_set_structured_feedback")).mock(
        return_value=_pg_error("P0001", "BAD_QUESTION", status_code=400)
    )

    resp = staff_client.put(
        f"{V2_ROOT}/admin/candidate-rounds/{CANDIDATE_ROUND_ID}/structured-feedback",
        json=_payload(),
    )
    assert resp.status_code == 400, resp.text


def test_structured_feedback_generic_rpc_failure_maps_error(staff_client, respx_mock):
    """A DB-level failure inside the RPC surfaces as a non-2xx, never a partial
    success."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_pre_read()])
    )
    _mock_questions(respx_mock)
    respx_mock.post(rpc_url("admin_set_structured_feedback")).mock(
        return_value=_pg_error("XX000", "internal error", status_code=500)
    )

    resp = staff_client.put(
        f"{V2_ROOT}/admin/candidate-rounds/{CANDIDATE_ROUND_ID}/structured-feedback",
        json=_payload(),
    )
    assert resp.status_code >= 400, resp.text
    assert resp.status_code != 200


def test_structured_feedback_404_when_cr_missing(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    rpc_route = respx_mock.post(rpc_url("admin_set_structured_feedback")).mock(
        return_value=httpx.Response(200, json=_rpc_envelope())
    )

    resp = staff_client.put(
        f"{V2_ROOT}/admin/candidate-rounds/{CANDIDATE_ROUND_ID}/structured-feedback",
        json=_payload(),
    )
    assert resp.status_code == 404, resp.text
    # Pre-read 404 must short-circuit before the RPC.
    assert not rpc_route.called
