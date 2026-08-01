"""Tests for POST /api/v2/internal/feedback/voice-complete.

Covers the stale-token rejection, the error-status branch, and the
completed-status branch that triggers the feedback Lambda. The internal-secret
guard is satisfied by overriding verify_internal_secret; supabase + the feedback
job service are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v2.core.dependencies import verify_internal_secret
from app.main import app

ENDPOINT = "/api/v2/internal/feedback/voice-complete"
CR_ID = "00000000-0000-0000-0000-0000000000aa"
TOKEN = "voice-token-1234567890"


@pytest.fixture
def client():
    app.dependency_overrides[verify_internal_secret] = lambda: None
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _update_supabase(affected_rows):
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("update", "eq", "in_"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=affected_rows))
    sb.table = MagicMock(return_value=builder)
    return sb


def test_voice_complete_stale_token_rejected(client):
    sb = _update_supabase([])  # zero rows updated -> stale
    with patch("app.api.v2.routers.internal_feedback.get_supabase_admin_client", return_value=sb):
        resp = client.post(ENDPOINT, json={
            "candidate_round_id": CR_ID, "voice_session_token": TOKEN,
            "transcript": "hello", "status": "completed",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["reason"] == "stale_or_already_terminal"


def test_voice_complete_error_status(client):
    sb = _update_supabase([{"id": CR_ID}])
    with patch("app.api.v2.routers.internal_feedback.get_supabase_admin_client", return_value=sb):
        resp = client.post(ENDPOINT, json={
            "candidate_round_id": CR_ID, "voice_session_token": TOKEN,
            "status": "error", "error_reason": "mic failed",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["processing_status"] is None


def test_voice_complete_completed_triggers_lambda(client):
    sb = _update_supabase([{"id": CR_ID}])
    feedback_service = MagicMock()
    feedback_service.trigger_feedback_processing = AsyncMock(return_value={"status": "accepted"})
    with patch("app.api.v2.routers.internal_feedback.get_supabase_admin_client", return_value=sb), \
         patch("app.api.v2.routers.internal_feedback.get_feedback_job_service", return_value=feedback_service):
        resp = client.post(ENDPOINT, json={
            "candidate_round_id": CR_ID, "voice_session_token": TOKEN,
            "transcript": "a real transcript", "status": "completed",
        })
    assert resp.status_code == 200
    assert resp.json()["processing_status"] == "processing"
    feedback_service.trigger_feedback_processing.assert_awaited_once_with(
        CR_ID, skip_prereq_check=True
    )


def test_voice_complete_lambda_failure_falls_back_to_pending(client):
    sb = _update_supabase([{"id": CR_ID}])
    feedback_service = MagicMock()
    feedback_service.trigger_feedback_processing = AsyncMock(side_effect=RuntimeError("lambda down"))
    with patch("app.api.v2.routers.internal_feedback.get_supabase_admin_client", return_value=sb), \
         patch("app.api.v2.routers.internal_feedback.get_feedback_job_service", return_value=feedback_service):
        resp = client.post(ENDPOINT, json={
            "candidate_round_id": CR_ID, "voice_session_token": TOKEN,
            "transcript": "x", "status": "completed",
        })
    assert resp.status_code == 200
    assert resp.json()["processing_status"] == "pending"


def test_voice_complete_lambda_not_accepted_is_pending(client):
    sb = _update_supabase([{"id": CR_ID}])
    feedback_service = MagicMock()
    feedback_service.trigger_feedback_processing = AsyncMock(return_value={"status": "skipped"})
    with patch("app.api.v2.routers.internal_feedback.get_supabase_admin_client", return_value=sb), \
         patch("app.api.v2.routers.internal_feedback.get_feedback_job_service", return_value=feedback_service):
        resp = client.post(ENDPOINT, json={
            "candidate_round_id": CR_ID, "voice_session_token": TOKEN,
            "transcript": "x", "status": "completed",
        })
    assert resp.status_code == 200
    assert resp.json()["processing_status"] == "pending"


def test_voice_complete_requires_internal_secret(unauthed_client):
    # No override here -> the real guard rejects (empty INTERNAL_API_SECRET fails closed).
    resp = unauthed_client.post(ENDPOINT, json={
        "candidate_round_id": CR_ID, "voice_session_token": TOKEN, "status": "completed",
    })
    assert resp.status_code in (401, 422)
