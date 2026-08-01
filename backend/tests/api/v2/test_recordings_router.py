"""
Tests for the v2 recordings router.

Endpoints under test:
  GET /candidate-rounds/{cr_id}/recording-url
  GET /candidate-rounds/{cr_id}/transcript

Both endpoints first scope the CR to the user's org. recording-url caches
on `recall_bots.recording_url` + `recording_url_expires_at` (migration 86)
and re-mints from Recall.ai when stale. Transcript serves cached segments
from the `transcripts` table when present.

Recall.ai is monkey-patched — no real network calls.
"""

import httpx
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
from tests.helpers.supabase_mocks import rest_url


V2_ROOT = "/api/v2"


def _make_cr_with_round(status_val="completed"):
    return {
        "id": CANDIDATE_ROUND_ID,
        "candidate_id": CANDIDATE_ID,
        "round_id": ROUND_ID,
        "status": status_val,
        "processing_status": "none",
        "scheduled_at": NOW,
        "completed_at": NOW if status_val == "completed" else None,
        "meeting_url": None,
        "interviewer_email": None,
        "rating": None,
        "summary": None,
        "scorecard_status": "pending",
        "created_at": NOW,
        "updated_at": NOW,
        "rounds": {
            "id": ROUND_ID,
            "assessment_template_id": None,
            "name": "Phone screen",
            "round_number": 1,
            "deleted_at": None,
        },
        "candidates": {
            "id": CANDIDATE_ID,
            "name": "Alice",
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


def _no_org_client():
    no_org_user = CurrentUser(
        id=UUID(RECRUITER_USER_ID),
        email="r@t.com",
        is_staff=False,
        organization_id=None,
    )
    app.dependency_overrides[get_current_user] = lambda: no_org_user
    return TestClient(app, raise_server_exceptions=False)


# ============================================================================
# GET /candidate-rounds/{cr_id}/recording-url
# ============================================================================


def test_recording_url_200_cache_hit(recruiter_client, respx_mock):
    """When the bot row has a cached URL and expires_at is in the future,
    we return the cache without calling Recall."""
    future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "00000000-0000-0000-0000-0000000000b1",
                    "recall_bot_id": "recall-bot-xyz",
                    "status": "done",
                    "recording_url": "https://cached.example.com/recording.mp4",
                    "recording_url_expires_at": future,
                }
            ],
        )
    )
    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["url"] == "https://cached.example.com/recording.mp4"
    assert "expires_at" in body


def test_recording_url_409_when_bot_not_done(recruiter_client, respx_mock):
    """Recording rendering isn't finished yet — surface 409 with bot_status
    so the FE can show "still processing" rather than a broken link."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "00000000-0000-0000-0000-0000000000b1",
                    "recall_bot_id": "recall-bot-xyz",
                    "status": "processing",
                    "recording_url": None,
                    "recording_url_expires_at": None,
                }
            ],
        )
    )
    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 409
    body = resp.json()
    # Detail payload is a dict, not a string — assert shape.
    assert "bot_status" in str(body)
    assert "processing" in str(body)


def test_recording_url_404_when_no_bot_exists(recruiter_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 404


def test_recording_url_re_mints_when_expires_at_in_past(
    recruiter_client, respx_mock, monkeypatch
):
    """Stale cache → call Recall, return fresh URL, write back to DB. The
    cache-write failure must NOT fail the request."""
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "00000000-0000-0000-0000-0000000000b1",
                    "recall_bot_id": "recall-bot-xyz",
                    "status": "done",
                    "recording_url": "https://stale.example.com/old.mp4",
                    "recording_url_expires_at": past,
                }
            ],
        )
    )
    # Cache write — succeeds.
    respx_mock.patch(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[])
    )

    class _FakeRecall:
        async def get_recording_urls(self, bot_id):
            return {"video_url": "https://fresh.example.com/new.mp4"}

        async def close(self):
            pass

    monkeypatch.setattr(
        "app.services.recall_service.get_recall_service",
        lambda: _FakeRecall(),
    )

    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"] == "https://fresh.example.com/new.mp4"


def test_recording_url_502_when_recall_throws(
    recruiter_client, respx_mock, monkeypatch
):
    """Recall API failure surfaces as 502 — never propagate the raw error."""
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "00000000-0000-0000-0000-0000000000b1",
                    "recall_bot_id": "recall-bot-xyz",
                    "status": "done",
                    "recording_url": None,
                    "recording_url_expires_at": past,
                }
            ],
        )
    )

    class _BrokenRecall:
        async def get_recording_urls(self, bot_id):
            raise RuntimeError("recall 503")

        async def close(self):
            pass

    monkeypatch.setattr(
        "app.services.recall_service.get_recall_service",
        lambda: _BrokenRecall(),
    )

    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 502


def test_recording_url_403_when_user_has_no_org():
    client = _no_org_client()
    try:
        resp = client.get(
            f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ============================================================================
# GET /candidate-rounds/{cr_id}/transcript
# ============================================================================


def test_transcript_200_returns_cached_segments(recruiter_client, respx_mock):
    """When `transcripts.segments` already has the flattened v2 shape, the
    endpoint returns it as-is. The transcript endpoint uses .single() on
    both queries — mocks must return objects, not arrays."""
    # Thin org-scope check on candidate_rounds (.single() wire shape).
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": CANDIDATE_ROUND_ID,
                    "candidates": {
                        "requisition_id": REQ_ID,
                        "requisitions": {"organization_id": ORG_ID},
                    },
                }
            ],
        )
    )
    respx_mock.get(rest_url("transcripts")).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "segments": [
                        {
                            "speaker": "Alice",
                            "text": "Hello there.",
                            "ts_start": 0.0,
                            "ts_end": 1.5,
                        }
                    ],
                    "duration_seconds": 1.5,
                    "word_count": 2,
                }
            ],
        )
    )
    # The service ALSO reads recall_bots to compute feedback_start_seconds
    # and decide whether to lazy-ingest. Empty array is fine — we have
    # cached segments, so no lazy-ingest path fires.
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/transcript"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "segments" in body
    assert body["segments"][0]["speaker"] == "Alice"
    assert body["segments"][0]["text"] == "Hello there."


def test_transcript_403_when_user_has_no_org():
    client = _no_org_client()
    try:
        resp = client.get(
            f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/transcript"
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_transcript_404_when_cr_cross_org(recruiter_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": CANDIDATE_ROUND_ID,
                    "candidates": {
                        "requisition_id": REQ_ID,
                        "requisitions": {
                            "organization_id": "ffffffff-ffff-ffff-ffff-ffffffffffff"
                        },
                    },
                }
            ],
        )
    )
    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/transcript"
    )
    assert resp.status_code in (403, 404)
