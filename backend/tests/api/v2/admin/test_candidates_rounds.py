"""BE-T1: admin candidate-round read/mutation coverage in candidates.py
(get_candidate_round, update_round_outcome, submit_feedback, transcript-status,
hiring-packet 404)."""
import httpx

from tests.helpers.supabase_mocks import rest_url, rpc_url
from tests.helpers.mock_data import (
    CANDIDATE_ID,
    CANDIDATE_ROUND_ID,
    ROUND_ID,
    REQ_ID,
    FEEDBACK_QUESTION_ID,
    NOW,
    make_candidate,
    make_round,
    make_candidate_round,
)

V2_ROOT = "/api/v2"
ADMIN = f"{V2_ROOT}/admin"


def _cr_with_round(status_val="completed"):
    return {
        "id": CANDIDATE_ROUND_ID,
        "candidate_id": CANDIDATE_ID,
        "round_id": ROUND_ID,
        "status": status_val,
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
            "description": "Tech",
        },
    }


def _question_row():
    return {
        "id": FEEDBACK_QUESTION_ID,
        "round_id": ROUND_ID,
        "heading": "Problem Solving",
        "question_number": 1,
        "description": "Eval",
    }


def _future_at():
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


# ── schedule_interview (no meeting_url → skips recall) ───────────────────────

def test_schedule_interview_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.put(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={"scheduled_at": _future_at()},
    )
    assert resp.status_code == 404, resp.text


def test_schedule_interview_success_no_meeting_url(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_with_round(status_val="pending")])
    )
    scheduled = _cr_with_round(status_val="scheduled")
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[scheduled])
    )
    resp = staff_client.put(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={"scheduled_at": _future_at()},
    )
    assert resp.status_code == 200, resp.text


# ── get_recording (no bot → not_scheduled) ───────────────────────────────────

def test_get_recording_not_scheduled(staff_client, respx_mock):
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "not_scheduled"


def test_get_recording_in_progress(staff_client, respx_mock):
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "status": "in_call_recording",
                "recall_bot_id": "ext-1",
                "scheduled_at": NOW,
                "joined_at": NOW,
                "left_at": None,
            }],
        )
    )
    respx_mock.get(rest_url("transcripts")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "in_call_recording"


# ── get_candidate_round ──────────────────────────────────────────────────────

def test_get_candidate_round_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}")
    assert resp.status_code == 404, resp.text


def test_get_candidate_round_success(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_with_round()])
    )
    respx_mock.get(rest_url("candidate_feedback")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[_question_row()])
    )
    resp = staff_client.get(f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["round_name"] == "Technical"
    assert len(body["feedback_questions"]) == 1


# ── update_round_outcome ─────────────────────────────────────────────────────

def test_update_round_outcome_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.put(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/outcome",
        json={"outcome": "advance"},
    )
    assert resp.status_code == 404, resp.text


def test_update_round_outcome_success(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_with_round()])
    )
    updated = _cr_with_round()
    updated["outcome"] = "advance"
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[updated])
    )
    resp = staff_client.put(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/outcome",
        json={"outcome": "advance", "outcome_notes": "good"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "advance"


# ── submit_feedback ──────────────────────────────────────────────────────────

def test_submit_feedback_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.put(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json={"feedback": [{"feedback_question_id": FEEDBACK_QUESTION_ID, "feedback_text": "x"}]},
    )
    assert resp.status_code == 404, resp.text


def test_submit_feedback_bad_question_400(staff_client, respx_mock):
    # Validation now happens transactionally inside the RPC (migration 106),
    # which raises P0001 BAD_QUESTION -> 400 with nothing written.
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ROUND_ID, "round_id": ROUND_ID}])
    )
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[])  # no valid questions
    )
    respx_mock.post(rpc_url("admin_submit_candidate_feedback")).mock(
        return_value=httpx.Response(
            400,
            json={"code": "P0001", "message": "BAD_QUESTION", "details": None, "hint": None},
        )
    )
    resp = staff_client.put(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json={"feedback": [{"feedback_question_id": FEEDBACK_QUESTION_ID, "feedback_text": "x"}]},
    )
    assert resp.status_code == 400, resp.text


def test_submit_feedback_success(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ROUND_ID, "round_id": ROUND_ID}])
    )
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[_question_row()])
    )
    # The atomic RPC returns the written rows in payload order (migration 106).
    respx_mock.post(rpc_url("admin_submit_candidate_feedback")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": "00000000-0000-0000-0000-0000000000e2",
                "feedback_question_id": FEEDBACK_QUESTION_ID,
                "feedback_text": "x",
                "evidence": [],
                "evidence_status": None,
                "source": "manual",
                "created_at": NOW,
                "updated_at": NOW,
            }],
        )
    )
    resp = staff_client.put(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json={"feedback": [{"feedback_question_id": FEEDBACK_QUESTION_ID, "feedback_text": "x"}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_submitted"] == 1


# ── transcript status ────────────────────────────────────────────────────────

def test_transcript_status_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/transcript-status"
    )
    assert resp.status_code == 404, resp.text


def test_transcript_status_success(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ROUND_ID}])
    )
    respx_mock.get(rest_url("transcripts")).mock(
        return_value=httpx.Response(
            200, json=[{"segments": [{"t": 1}], "feedback_transcript": None}]
        )
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/transcript-status"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_transcript"] is True
    assert body["has_interview_segments"] is True


# ── hiring packet 404 ────────────────────────────────────────────────────────

def test_get_candidate_hiring_packet_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(f"{ADMIN}/candidates/{CANDIDATE_ID}")
    assert resp.status_code == 404, resp.text


def test_get_candidate_hiring_packet_success(staff_client, respx_mock):
    """Exercises the full hiring-packet assembly (no assessment template)."""
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[make_candidate()])
    )
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[{"role_title": "Software Engineer"}])
    )
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[make_round()])
    )
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[make_candidate_round(status="completed")])
    )
    respx_mock.get(rest_url("candidate_feedback")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[_question_row()])
    )
    resp = staff_client.get(f"{ADMIN}/candidates/{CANDIDATE_ID}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["requisition_title"] == "Software Engineer"
    assert body["overall_progress"] == "1/1 rounds completed"
    assert len(body["rounds"]) == 1
