"""Tests for POST /api/v2/internal/screening/voice-complete.

The voice agent (Task 8) calls here when a screening call ends. The route does a
CAS update of the screening voice-session status (scoped by id + token +
non-terminal status), nulls the token (replay protection), and on completion
persists the interview transcript to `transcripts.segments` and schedules the AI
feedback generator off the request path via BackgroundTasks.

The internal-secret guard is satisfied by overriding verify_internal_secret;
supabase, the upsert path and the feedback generator are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v2.core.dependencies import verify_internal_secret
from app.main import app

ENDPOINT = "/api/v2/internal/screening/voice-complete"
CR_ID = "00000000-0000-0000-0000-0000000000aa"
TOKEN = "11111111-1111-1111-1111-111111111111"
TRANSCRIPT = "Scout Interviewer: Tell me about a hard project.\n\nCandidate: I led a migration."


@pytest.fixture
def client():
    app.dependency_overrides[verify_internal_secret] = lambda: None
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _supabase(cas_rows):
    """Fluent supabase mock. The CAS update returns `cas_rows`; every other
    builder call (upsert for transcripts) is a no-op returning data=[{...}]."""
    builder = MagicMock()
    for attr in ("table", "update", "eq", "in_", "is_", "select", "single"):
        setattr(builder, attr, MagicMock(return_value=builder))
    # CAS update path.
    builder.execute_async = AsyncMock(return_value=MagicMock(data=cas_rows))
    # transcripts upsert path.
    upsert_builder = MagicMock()
    upsert_builder.execute_async = AsyncMock(return_value=MagicMock(data=[{"id": "t1"}]))
    builder.upsert = MagicMock(return_value=upsert_builder)
    sb = MagicMock()
    sb.table = MagicMock(return_value=builder)
    return sb, builder, upsert_builder


def test_voice_complete_requires_internal_secret(unauthed_client):
    resp = unauthed_client.post(
        ENDPOINT,
        json={
            "candidate_round_id": CR_ID,
            "voice_session_token": TOKEN,
            "transcript": TRANSCRIPT,
            "status": "completed",
        },
    )
    assert resp.status_code in (401, 422)


def test_voice_complete_stale_token_no_op(client):
    sb, _, upsert_builder = _supabase([])  # zero rows -> stale/superseded
    gen = MagicMock()
    gen.generate_and_dispatch = AsyncMock()
    with patch(
        "app.api.v2.routers.internal_screening.get_supabase_admin_client",
        return_value=sb,
    ), patch(
        "app.api.v2.routers.internal_screening.get_screening_feedback_service",
        return_value=gen,
    ):
        resp = client.post(
            ENDPOINT,
            json={
                "candidate_round_id": CR_ID,
                "voice_session_token": TOKEN,
                "transcript": TRANSCRIPT,
                "status": "completed",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["reason"] == "stale_or_superseded"
    # No transcript persisted, no feedback generation scheduled on a stale token.
    upsert_builder.execute_async.assert_not_awaited()
    gen.generate_and_dispatch.assert_not_awaited()


def test_voice_complete_error_status(client):
    sb, builder, upsert_builder = _supabase([{"id": CR_ID}])
    with patch(
        "app.api.v2.routers.internal_screening.get_supabase_admin_client",
        return_value=sb,
    ):
        resp = client.post(
            ENDPOINT,
            json={
                "candidate_round_id": CR_ID,
                "voice_session_token": TOKEN,
                "status": "error",
                "error_reason": "mic failed",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # The CAS update sets the error status.
    update_payloads = [c.args[0] for c in builder.update.call_args_list]
    assert any(
        p.get("screening_voice_session_status") == "error" for p in update_payloads
    )
    # No transcript and no scoring on error.
    upsert_builder.execute_async.assert_not_awaited()


def test_voice_complete_persists_segments_and_schedules(client):
    sb, builder, upsert_builder = _supabase([{"id": CR_ID}])
    gen = MagicMock()
    gen.generate_and_dispatch = AsyncMock()
    with patch(
        "app.api.v2.routers.internal_screening.get_supabase_admin_client",
        return_value=sb,
    ), patch(
        "app.api.v2.routers.internal_screening.get_screening_feedback_service",
        return_value=gen,
    ):
        resp = client.post(
            ENDPOINT,
            json={
                "candidate_round_id": CR_ID,
                "voice_session_token": TOKEN,
                "transcript": TRANSCRIPT,
                "status": "completed",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Transcript persisted via upsert into transcripts.
    builder.upsert.assert_called_once()
    upsert_payload = builder.upsert.call_args.args[0]
    assert upsert_payload["candidate_round_id"] == CR_ID
    segments = upsert_payload["segments"]
    assert isinstance(segments, list) and len(segments) == 2
    assert segments[0]["speaker"] == "Scout Interviewer"
    assert "hard project" in segments[0]["text"]
    assert segments[1]["speaker"] == "Candidate"
    assert "migration" in segments[1]["text"]
    # Shape the Lambda consumes: simple {"speaker","text"} dicts.
    assert set(segments[0].keys()) >= {"speaker", "text"}

    # Background task scheduled (TestClient runs background tasks after response).
    gen.generate_and_dispatch.assert_awaited_once_with(CR_ID)


def test_voice_complete_second_call_is_stale_no_reschedule(client):
    """Idempotency / two-trigger race: a SECOND completion for the same round
    after the first nulled the token is rejected by the CAS (zero rows) and must
    NOT re-schedule feedback generation.

    Simulated by the CAS returning a matched row on the first call (the token was
    live) and zero rows on the second (the token is now NULL / status terminal),
    which is exactly what the real DB does after the first completion's CAS write.
    """
    # First CAS matches a row, second CAS finds none (token nulled / terminal).
    cas_results = [MagicMock(data=[{"id": CR_ID}]), MagicMock(data=[])]
    builder = MagicMock()
    for attr in ("table", "update", "eq", "in_", "is_", "select", "single"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(side_effect=cas_results)
    upsert_builder = MagicMock()
    upsert_builder.execute_async = AsyncMock(return_value=MagicMock(data=[{"id": "t1"}]))
    builder.upsert = MagicMock(return_value=upsert_builder)
    sb = MagicMock()
    sb.table = MagicMock(return_value=builder)

    gen = MagicMock()
    gen.generate_and_dispatch = AsyncMock()

    payload = {
        "candidate_round_id": CR_ID,
        "voice_session_token": TOKEN,
        "transcript": TRANSCRIPT,
        "status": "completed",
    }
    with patch(
        "app.api.v2.routers.internal_screening.get_supabase_admin_client",
        return_value=sb,
    ), patch(
        "app.api.v2.routers.internal_screening.get_screening_feedback_service",
        return_value=gen,
    ):
        first = client.post(ENDPOINT, json=payload)
        second = client.post(ENDPOINT, json=payload)

    # First completion succeeds and schedules feedback exactly once.
    assert first.status_code == 200
    assert first.json()["success"] is True
    # Second completion is rejected as stale/superseded.
    assert second.status_code == 200
    assert second.json()["success"] is False
    assert second.json()["reason"] == "stale_or_superseded"

    # Feedback generation scheduled exactly ONCE across both calls — the stale
    # second completion does not re-trigger the Lambda dispatch path.
    gen.generate_and_dispatch.assert_awaited_once_with(CR_ID)
    # The second call's transcript never reaches the upsert (only the first did).
    assert builder.upsert.call_count == 1
