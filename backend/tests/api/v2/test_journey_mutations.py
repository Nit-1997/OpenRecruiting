"""
Tests for the role-detail v2 candidate-round journey mutation endpoints
(PR 4b: schedule, reschedule, cancel, feedback, request-feedback, reprocess).

Spec: docs/superpowers/specs/2026-05-18-roles-detail-v2-api-design.md §8.2

Mocks Supabase HTTP via respx; mocks Recall + Lambda + the feedback
notification service via monkeypatch. No real external API calls.

Test naming: each block targets one endpoint per spec row.
"""

import json
import httpx
import pytest
from datetime import datetime, timedelta, timezone
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

# Always-future scheduled_at, computed at import time. The schedule schema's
# `_reject_scheduled_in_past` validator (interview.py) rejects timestamps more
# than 60s in the past, so a hard-coded literal rots into a 422 once wall-clock
# passes it. Tests below that exercise non-validation branches (200/404/409, and
# the RPC-side 400 past-time guard) must send a timestamp that the schema
# accepts. The dedicated 422 past-time tests intentionally send a 2020 literal.
_FUTURE_AT = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


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


def _make_cr_with_round(
    *,
    status_val: str = "pending",
    processing_status: str = "none",
    assessment_template_id=None,
    meeting_url=None,
):
    """Shape the candidate_rounds + embedded rounds/candidates/requisitions
    join that _load_cr_with_round_for_org expects."""
    return {
        "id": CANDIDATE_ROUND_ID,
        "candidate_id": CANDIDATE_ID,
        "round_id": ROUND_ID,
        "status": status_val,
        "processing_status": processing_status,
        "scheduled_at": None if status_val == "pending" else NOW,
        "completed_at": NOW if status_val == "completed" else None,
        "meeting_url": meeting_url,
        "interviewer_email": None,
        "rating": None,
        "summary": None,
        "scorecard_status": "pending",
        "created_at": NOW,
        "updated_at": NOW,
        "rounds": {
            "id": ROUND_ID,
            "assessment_template_id": assessment_template_id,
            "name": "Phone screen",
            "round_number": 1,
            "deleted_at": None,
        },
        "candidates": {
            "id": CANDIDATE_ID,
            "name": "Alice Example",
            "email": "alice@example.com",
            "requisition_id": REQ_ID,
            "deleted_at": None,
            "requisitions": {
                "id": REQ_ID,
                "organization_id": ORG_ID,
                "status": "planned",
                "deleted_at": None,
            },
        },
    }


# ============================================================================
# Endpoint 1 — POST /candidate-rounds/{cr_id}/schedule
# ============================================================================


def test_schedule_200_with_bot_creation(recruiter_client, respx_mock, monkeypatch):
    captured = {}

    # Pre-flight CR load
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="pending")])
    )

    def _capture_rpc(request):
        captured["rpc_body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "candidate_round": {
                **_make_cr_with_round(status_val="scheduled", meeting_url="https://meet.google.com/abc-defg-hij"),
                "rounds": None, "candidates": None,
            },
            "assessment_instance": None,
            "candidate_name": "Alice Example",
        })

    respx_mock.post(rpc_url("schedule_candidate_round")).mock(side_effect=_capture_rpc)

    # Stub the Recall orchestration to succeed.
    async def fake_create_bot(*args, **kwargs):
        return {
            "id": "bot-row-uuid",
            "recall_bot_id": "recall-bot-1",
            "status": "created",
            "meeting_url": "https://meet.google.com/abc-defg-hij",
            "scheduled_at": _FUTURE_AT,
        }

    monkeypatch.setattr(
        "app.api.v2.services.recall_orchestrator.create_recall_bot_for_cr", fake_create_bot
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={
            "scheduled_at": _FUTURE_AT,
            "interviewer_email": "i@example.com",
            "meeting_url": "https://meet.google.com/abc-defg-hij",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_round"]["status"] == "scheduled"
    assert body["bot"]["recall_bot_id"] == "recall-bot-1"
    assert body["assessment_instance"] is None

    rpc_body = captured["rpc_body"]
    assert rpc_body["p_cr_id"] == CANDIDATE_ROUND_ID
    assert rpc_body["p_org_id"] == ORG_ID
    assert rpc_body["p_interviewer_email"] == "i@example.com"
    assert rpc_body["p_meeting_url"] == "https://meet.google.com/abc-defg-hij"
    # No template → no instance payload
    assert rpc_body["p_assessment_instance"] is None


def test_schedule_200_with_assessment_instance(recruiter_client, respx_mock, monkeypatch):
    captured = {}

    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[
            _make_cr_with_round(status_val="pending", assessment_template_id="11111111-1111-1111-1111-111111111111")
        ])
    )

    def _capture_rpc(request):
        captured["rpc_body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "candidate_round": {
                **_make_cr_with_round(status_val="scheduled"),
                "rounds": None, "candidates": None,
            },
            "assessment_instance": {
                "id": "inst_abc12345",
                "template_id": "11111111-1111-1111-1111-111111111111",
                "candidate_id": CANDIDATE_ID,
                "round_id": ROUND_ID,
                "candidate_email": "alice@example.com",
                "candidate_name": "Alice Example",
                "access_code": "REDACTED",
                "access_code_hash": "x",
                "access_code_expires_at": "2026-06-04T10:00:00+00:00",
                "status": "pending",
                "expires_at": "2026-06-04T10:00:00+00:00",
            },
            "candidate_name": "Alice Example",
        })

    respx_mock.post(rpc_url("schedule_candidate_round")).mock(side_effect=_capture_rpc)

    # No meeting_url → no bot creation expected.

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={
            "scheduled_at": _FUTURE_AT,
            "interviewer_email": "i@example.com",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["assessment_instance"]["id"].startswith("inst_")
    assert body["bot"] is None

    # Verify the handler built and forwarded the instance payload to the RPC.
    rpc_body = captured["rpc_body"]
    instance_payload = rpc_body["p_assessment_instance"]
    assert instance_payload is not None
    assert instance_payload["template_id"] == "11111111-1111-1111-1111-111111111111"
    assert instance_payload["candidate_email"] == "alice@example.com"
    assert len(instance_payload["access_code"]) == 8
    assert "access_code_hash" in instance_payload


def test_schedule_200_when_bot_creation_fails(recruiter_client, respx_mock, monkeypatch):
    """A Recall failure must NOT roll back the DB write — return 200 with bot=null."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="pending")])
    )

    respx_mock.post(rpc_url("schedule_candidate_round")).mock(
        return_value=httpx.Response(200, json={
            "candidate_round": {
                **_make_cr_with_round(status_val="scheduled", meeting_url="https://zoom.us/j/123"),
                "rounds": None, "candidates": None,
            },
            "assessment_instance": None,
            "candidate_name": "Alice Example",
        })
    )

    async def fake_create_bot(*args, **kwargs):
        return None  # simulated Recall failure

    monkeypatch.setattr(
        "app.api.v2.services.recall_orchestrator.create_recall_bot_for_cr", fake_create_bot
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={
            "scheduled_at": _FUTURE_AT,
            "interviewer_email": "i@example.com",
            "meeting_url": "https://zoom.us/j/123",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_round"]["status"] == "scheduled"
    assert body["bot"] is None


def test_schedule_409_when_completed(recruiter_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="completed")])
    )
    respx_mock.post(rpc_url("schedule_candidate_round")).mock(
        return_value=_pg_error("P0001", "NOT_SCHEDULABLE")
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={
            "scheduled_at": _FUTURE_AT,
            "interviewer_email": "i@example.com",
        },
    )
    assert resp.status_code == 409
    assert "schedulable" in resp.json()["detail"].lower()


def test_schedule_409_when_requisition_closed(recruiter_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="pending")])
    )
    respx_mock.post(rpc_url("schedule_candidate_round")).mock(
        return_value=_pg_error("P0001", "REQ_CLOSED")
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={
            "scheduled_at": _FUTURE_AT,
            "interviewer_email": "i@example.com",
        },
    )
    assert resp.status_code == 409
    assert "closed" in resp.json()["detail"].lower()


def test_schedule_404_when_cr_not_in_org(recruiter_client, respx_mock):
    # Pre-flight load returns a CR in a different org → 404.
    cr = _make_cr_with_round(status_val="pending")
    cr["candidates"]["requisitions"]["organization_id"] = "00000000-0000-0000-0000-00000000ffff"
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[cr])
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={
            "scheduled_at": _FUTURE_AT,
            "interviewer_email": "i@example.com",
        },
    )
    assert resp.status_code == 404


def test_schedule_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(
            f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
            json={
                "scheduled_at": _FUTURE_AT,
                "interviewer_email": "i@example.com",
            },
        )
    assert resp.status_code == 403


# ============================================================================
# Endpoint 2 — PUT /candidate-rounds/{cr_id}/schedule (reschedule)
# ============================================================================


def test_reschedule_200_url_change_recreates_bot(recruiter_client, respx_mock, monkeypatch):
    captured = {}
    cancel_called = {"n": 0}
    create_called = {"n": 0}

    def _capture_rpc(request):
        captured["rpc_body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "candidate_round": {
                **_make_cr_with_round(
                    status_val="scheduled",
                    meeting_url="https://meet.google.com/new-url-aaa",
                ),
                "rounds": None, "candidates": None,
            },
            "prev_meeting_url": "https://meet.google.com/old-url-bbb",
            "candidate_name": "Alice Example",
        })

    respx_mock.post(rpc_url("reschedule_candidate_round")).mock(side_effect=_capture_rpc)

    async def fake_cancel(cr_id):
        cancel_called["n"] += 1

    async def fake_create(*args, **kwargs):
        create_called["n"] += 1
        return {"id": "bot-2", "recall_bot_id": "rb-2", "status": "created"}

    monkeypatch.setattr("app.api.v2.services.recall_orchestrator.cancel_recall_bot_for_cr", fake_cancel)
    monkeypatch.setattr("app.api.v2.services.recall_orchestrator.create_recall_bot_for_cr", fake_create)

    resp = recruiter_client.put(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={
            "scheduled_at": _FUTURE_AT,
            "meeting_url": "https://meet.google.com/new-url-aaa",
        },
    )
    assert resp.status_code == 200, resp.text
    assert cancel_called["n"] == 1
    assert create_called["n"] == 1
    assert resp.json()["bot"]["recall_bot_id"] == "rb-2"


def test_reschedule_200_fields_only_no_bot_change(recruiter_client, respx_mock, monkeypatch):
    cancel_called = {"n": 0}
    create_called = {"n": 0}

    respx_mock.post(rpc_url("reschedule_candidate_round")).mock(
        return_value=httpx.Response(200, json={
            "candidate_round": {
                **_make_cr_with_round(
                    status_val="scheduled",
                    meeting_url="https://meet.google.com/unchanged-url",
                ),
                "rounds": None, "candidates": None,
            },
            "prev_meeting_url": "https://meet.google.com/unchanged-url",
            "candidate_name": "Alice Example",
        })
    )

    async def fake_cancel(cr_id):
        cancel_called["n"] += 1

    async def fake_create(*args, **kwargs):
        create_called["n"] += 1
        return {}

    monkeypatch.setattr("app.api.v2.services.recall_orchestrator.cancel_recall_bot_for_cr", fake_cancel)
    monkeypatch.setattr("app.api.v2.services.recall_orchestrator.create_recall_bot_for_cr", fake_create)

    resp = recruiter_client.put(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={"scheduled_at": _FUTURE_AT},
    )
    assert resp.status_code == 200, resp.text
    # url unchanged → no bot cleanup/recreate
    assert cancel_called["n"] == 0
    assert create_called["n"] == 0
    assert resp.json()["bot"] is None


def test_reschedule_409_when_not_scheduled(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("reschedule_candidate_round")).mock(
        return_value=_pg_error("P0001", "NOT_RESCHEDULABLE")
    )
    resp = recruiter_client.put(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={"scheduled_at": _FUTURE_AT},
    )
    assert resp.status_code == 409


def test_reschedule_404_when_not_found(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("reschedule_candidate_round")).mock(
        return_value=_pg_error("P0002", "NOT_FOUND")
    )
    resp = recruiter_client.put(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={"scheduled_at": _FUTURE_AT},
    )
    assert resp.status_code == 404


def test_reschedule_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.put(
            f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
            json={"scheduled_at": _FUTURE_AT},
        )
    assert resp.status_code == 403


# ============================================================================
# scheduled_at-in-the-past validation (Pydantic schema + RPC defence-in-depth)
# ============================================================================


def test_schedule_422_when_scheduled_in_past(recruiter_client, respx_mock):
    """A scheduled_at clearly in the past must 422 before reaching the RPC.
    Mirrors the 60-second grace in migration 87's RPC guard."""
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={
            "scheduled_at": "2020-01-01T10:00:00+00:00",
            "interviewer_email": "i@example.com",
        },
    )
    assert resp.status_code == 422
    # FastAPI's default validation error envelope. The field path should
    # mention scheduled_at so a FE form can surface it inline.
    body = resp.json()
    assert "scheduled_at" in json.dumps(body)


def test_reschedule_422_when_scheduled_in_past(recruiter_client, respx_mock):
    """Reschedule's past-time guard applies only when scheduled_at is
    provided (partial PUT may omit it)."""
    resp = recruiter_client.put(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={"scheduled_at": "2020-01-01T10:00:00+00:00"},
    )
    assert resp.status_code == 422


def test_schedule_400_when_rpc_raises_scheduled_in_past(
    recruiter_client, respx_mock
):
    """Belt + suspenders: if the FE somehow sneaks a stale scheduled_at past
    the Pydantic schema (e.g. the user kept the modal open for an hour and
    clicked submit), the RPC guard raises P0001 SCHEDULED_IN_PAST. The v2
    domain `ValidationError` handler returns 400 (the FE's toServiceError
    treats 400 and 422 the same — both become `validation`)."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="pending")])
    )
    respx_mock.post(rpc_url("schedule_candidate_round")).mock(
        return_value=_pg_error("P0001", "SCHEDULED_IN_PAST")
    )

    # Use a future timestamp so the schema lets it through; the mocked RPC
    # is what surfaces the error.
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/schedule",
        json={
            "scheduled_at": _FUTURE_AT,
            "interviewer_email": "i@example.com",
        },
    )
    assert resp.status_code == 400
    assert "past" in resp.json()["detail"].lower()


# ============================================================================
# Endpoint 3 — POST /candidate-rounds/{cr_id}/cancel
# ============================================================================


def test_cancel_200(recruiter_client, respx_mock, monkeypatch):
    cancel_called = {"n": 0}

    respx_mock.post(rpc_url("cancel_candidate_round")).mock(
        return_value=httpx.Response(200, json={
            "candidate_round": {
                **_make_cr_with_round(status_val="cancelled"),
                "rounds": None, "candidates": None,
            }
        })
    )

    async def fake_cancel(cr_id):
        cancel_called["n"] += 1

    monkeypatch.setattr("app.api.v2.services.recall_orchestrator.cancel_recall_bot_for_cr", fake_cancel)

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/cancel"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidate_round"]["status"] == "cancelled"
    assert cancel_called["n"] == 1


def test_cancel_200_idempotent(recruiter_client, respx_mock, monkeypatch):
    """RPC returns the already-cancelled row without raising — Python wrapper
    should still return 200."""
    respx_mock.post(rpc_url("cancel_candidate_round")).mock(
        return_value=httpx.Response(200, json={
            "candidate_round": {
                **_make_cr_with_round(status_val="cancelled"),
                "rounds": None, "candidates": None,
            }
        })
    )

    async def fake_cancel(cr_id):
        return

    monkeypatch.setattr("app.api.v2.services.recall_orchestrator.cancel_recall_bot_for_cr", fake_cancel)

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/cancel"
    )
    assert resp.status_code == 200


def test_cancel_409_when_completed(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("cancel_candidate_round")).mock(
        return_value=_pg_error("P0001", "ALREADY_COMPLETED")
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/cancel"
    )
    assert resp.status_code == 409
    assert "completed" in resp.json()["detail"].lower()


def test_cancel_404_when_not_found(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("cancel_candidate_round")).mock(
        return_value=_pg_error("P0002", "NOT_FOUND")
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/cancel"
    )
    assert resp.status_code == 404


def test_cancel_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/cancel")
    assert resp.status_code == 403


# ============================================================================
# Endpoint 4 — POST /candidate-rounds/{cr_id}/feedback (human submit)
# ============================================================================


def test_submit_feedback_200(recruiter_client, respx_mock):
    captured = {}

    def _capture(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "candidate_round": {
                **_make_cr_with_round(status_val="completed"),
                "rounds": None, "candidates": None,
                "rating": "yes", "summary": "Solid candidate.",
                "scorecard_status": "complete",
            },
            "entries": [
                {
                    "id": "00000000-0000-0000-0000-0000000000a1",
                    "candidate_round_id": CANDIDATE_ROUND_ID,
                    "feedback_question_id": "00000000-0000-0000-0000-000000000060",
                    "feedback_text": "Strong system design.",
                    "evidence": [],
                    "evidence_status": "supported",
                    "source": "manual",
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ],
        })

    respx_mock.post(rpc_url("submit_human_feedback")).mock(side_effect=_capture)

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json={
            "entries": [
                {
                    "feedback_question_id": "00000000-0000-0000-0000-000000000060",
                    "feedback_text": "Strong system design.",
                    "evidence_status": "supported",
                    "evidence": ["q1"],
                }
            ],
            "rating": "yes",
            "summary": "Solid candidate.",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_round"]["status"] == "completed"
    assert body["candidate_round"]["rating"] == "yes"
    assert len(body["entries"]) == 1
    assert body["entries"][0]["source"] == "manual"

    sent = captured["body"]
    assert sent["p_rating"] == "yes"
    assert sent["p_summary"] == "Solid candidate."
    assert sent["p_entries"][0]["evidence_status"] == "supported"


def test_submit_feedback_400_when_bad_question(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("submit_human_feedback")).mock(
        return_value=_pg_error("P0001", "BAD_QUESTION")
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json={
            "entries": [
                {
                    "feedback_question_id": "00000000-0000-0000-0000-000000000060",
                    "feedback_text": "x",
                    "evidence_status": "supported",
                }
            ],
            "rating": "maybe",
            "summary": "x",
        },
    )
    assert resp.status_code == 400
    assert "belong" in resp.json()["detail"].lower() or "question" in resp.json()["detail"].lower()


def test_submit_feedback_409_when_not_open(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("submit_human_feedback")).mock(
        return_value=_pg_error("P0001", "NOT_OPEN")
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json={
            "entries": [],
            "rating": "yes",
            "summary": "x",
        },
    )
    assert resp.status_code == 409


def test_submit_feedback_404_when_not_found(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("submit_human_feedback")).mock(
        return_value=_pg_error("P0002", "NOT_FOUND")
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json={
            "entries": [],
            "rating": "yes",
            "summary": "x",
        },
    )
    assert resp.status_code == 404


def test_submit_feedback_422_when_invalid_rating(recruiter_client, respx_mock):
    """Pydantic Literal must reject ratings that aren't in the DB enum."""
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json={
            "entries": [],
            "rating": "amazing",  # NOT a DB value
            "summary": "x",
        },
    )
    assert resp.status_code == 422


def test_submit_feedback_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(
            f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
            json={"entries": [], "rating": "yes", "summary": "x"},
        )
    assert resp.status_code == 403


# ============================================================================
# Endpoint 5 — POST /candidate-rounds/{cr_id}/request-feedback
# ============================================================================


def test_request_feedback_200_via_email(recruiter_client, respx_mock, monkeypatch):
    """Email channel routes through FeedbackNotificationService."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="scheduled")])
    )
    # interviewer_email update
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    # Patch the notification service factory to return a stub.
    class FakeNotificationService:
        async def _get_candidate_round_context(self, cr_id):
            return {"candidate_name": "Alice Example", "requisition_id": REQ_ID}

        async def send_capture_request_to_interviewer(self, tup, ctx, cr_id):
            return {"sent": True, "message_id": "msg-123"}

    monkeypatch.setattr(
        "app.services.feedback_notification_service.get_feedback_notification_service",
        lambda: FakeNotificationService(),
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
        json={"interviewer_email": "i@example.com", "channel": "email"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is True
    assert body["request_id"] == "msg-123"
    assert body["channel"] == "email"


def test_request_feedback_501_when_slack_channel(recruiter_client, respx_mock):
    """Slack channel is not wired yet — surface 501 explicitly."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="scheduled")])
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
        json={"interviewer_email": "i@example.com", "channel": "slack"},
    )
    assert resp.status_code == 501


def test_request_feedback_404_when_cr_not_found(recruiter_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
        json={"interviewer_email": "i@example.com", "channel": "email"},
    )
    assert resp.status_code == 404


def test_request_feedback_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(
            f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
            json={"interviewer_email": "i@example.com", "channel": "email"},
        )
    assert resp.status_code == 403


# ============================================================================
# Endpoint 6 — POST /candidate-rounds/{cr_id}/reprocess
# ============================================================================


def test_reprocess_200_when_completed(recruiter_client, respx_mock, monkeypatch):
    cr = _make_cr_with_round(status_val="completed", processing_status="completed")
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[cr])
    )

    captured = {}

    class FakeFeedbackJobService:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            captured["cr_id"] = cr_id
            captured["skip_prereq_check"] = skip_prereq_check
            return {"status": "accepted", "candidate_round_id": cr_id}

    monkeypatch.setattr(
        "app.services.feedback_job_service.get_feedback_job_service",
        lambda: FakeFeedbackJobService(),
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
        json={},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_round_id"] == CANDIDATE_ROUND_ID
    assert body["processing_status"] == "processing"
    assert "triggered_at" in body
    # default force=false → skip_prereq_check=False
    assert captured["skip_prereq_check"] is False


def test_reprocess_400_when_not_completed(recruiter_client, respx_mock):
    cr = _make_cr_with_round(status_val="scheduled", processing_status="none")
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[cr])
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
        json={},
    )
    assert resp.status_code == 400
    assert "completed" in resp.json()["detail"].lower()


def test_reprocess_409_when_processing_and_not_forced(recruiter_client, respx_mock):
    cr = _make_cr_with_round(status_val="completed", processing_status="processing")
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[cr])
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
        json={"force": False},
    )
    assert resp.status_code == 409
    assert "flight" in resp.json()["detail"].lower() or "processing" in resp.json()["detail"].lower()


def test_reprocess_200_when_processing_and_forced(recruiter_client, respx_mock, monkeypatch):
    """force=true bypasses the in-flight guard and MUST pass skip_prereq_check=True
    to FeedbackJobService (CLAUDE.md Lambda Code Mandatory Rules, May 2026 1ecc51c1)."""
    cr = _make_cr_with_round(status_val="completed", processing_status="processing")
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[cr])
    )

    captured = {}

    class FakeFeedbackJobService:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            captured["cr_id"] = cr_id
            captured["skip_prereq_check"] = skip_prereq_check
            return {"status": "accepted", "candidate_round_id": cr_id}

    monkeypatch.setattr(
        "app.services.feedback_job_service.get_feedback_job_service",
        lambda: FakeFeedbackJobService(),
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
        json={"force": True},
    )
    assert resp.status_code == 200, resp.text
    assert captured["cr_id"] == CANDIDATE_ROUND_ID
    # CRITICAL: skip_prereq_check must be True when force=True.
    assert captured["skip_prereq_check"] is True


def test_reprocess_404_when_cr_not_found(recruiter_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
        json={},
    )
    assert resp.status_code == 404


def test_reprocess_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.post(
            f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
            json={},
        )
    assert resp.status_code == 403
