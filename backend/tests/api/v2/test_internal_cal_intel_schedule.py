"""Behavioral coverage for the internal Calendar Intelligence schedule endpoint
(`POST /api/v2/internal/calendar-intelligence/schedule`) and its compensating
rollback in `app/api/v2/routers/internal_calendar_intelligence.py`.

The handler is a multi-step orchestration with a CAS claim, candidate
create/reuse, candidate-round upsert, optional bot/transcript linking, and a
final CAS confirm — each guarded by a rollback path. These tests drive the
happy path plus the rollback when the final CAS confirm loses the race.

All Supabase IO is mocked via respx using per-route side_effect sequences so a
table hit multiple times (e.g. `calendar_event_detections` for select → claim →
confirm) returns the right response in order.
"""
import httpx
import pytest

from app.config import get_settings
from tests.helpers.mock_data import ORG_ID, REQ_ID, ROUND_ID, CANDIDATE_ID, CANDIDATE_ROUND_ID
from tests.helpers.supabase_mocks import rest_url

SCHEDULE_PATH = "/api/v2/internal/calendar-intelligence/schedule"
SECRET = "cal-intel-internal-secret"
DETECTION_ID = "00000000-0000-0000-0000-0000000000c0"


@pytest.fixture
def cal_intel_settings(monkeypatch):
    """Force a known INTERNAL_API_SECRET and enable the feature so the guard +
    feature-flag both pass for happy-path tests."""
    settings = get_settings()
    monkeypatch.setattr(settings, "INTERNAL_API_SECRET", SECRET)
    monkeypatch.setattr(settings, "CALENDAR_INTELLIGENCE_ENABLED", True)
    return settings


def _headers():
    return {"X-Internal-Secret": SECRET}


def _body(**overrides):
    body = {
        "detection_id": DETECTION_ID,
        "candidate_name": "Jane Cand",
        "candidate_email": "jane@example.com",
        "requisition_id": REQ_ID,
        "round_id": ROUND_ID,
        "meeting_url": "https://zoom.us/j/999",
        "scheduled_at": "2025-02-01T15:00:00+00:00",
    }
    body.update(overrides)
    return body


def _seq(*responses):
    """respx side_effect helper returning each response in order."""
    it = iter(responses)
    return lambda request: next(it)


# ---------------------------------------------------------------------------
# guard / feature-flag
# ---------------------------------------------------------------------------


def test_schedule_403_without_secret(unauthed_client):
    resp = unauthed_client.post(SCHEDULE_PATH, json=_body())
    assert resp.status_code == 403


def test_schedule_403_wrong_secret(unauthed_client, cal_intel_settings):
    resp = unauthed_client.post(
        SCHEDULE_PATH, headers={"X-Internal-Secret": "nope"}, json=_body()
    )
    assert resp.status_code == 403


def test_schedule_503_when_feature_disabled(unauthed_client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "INTERNAL_API_SECRET", SECRET)
    monkeypatch.setattr(settings, "CALENDAR_INTELLIGENCE_ENABLED", False)
    resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# early validation branches
# ---------------------------------------------------------------------------


def test_schedule_404_detection_not_found(unauthed_client, cal_intel_settings, respx_mock):
    respx_mock.get(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Detection not found"


def test_schedule_409_terminal_status(unauthed_client, cal_intel_settings, respx_mock):
    respx_mock.get(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": DETECTION_ID,
                "detection_status": "confirmed",  # terminal, not schedulable
                "organization_id": ORG_ID,
                "profile_id": "p1",
            }],
        )
    )
    resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())
    assert resp.status_code == 409
    assert "terminal state" in resp.json()["detail"]


def test_schedule_409_cas_claim_lost(unauthed_client, cal_intel_settings, respx_mock):
    respx_mock.get(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": DETECTION_ID,
                "detection_status": "detected",
                "organization_id": ORG_ID,
                "profile_id": "p1",
            }],
        )
    )
    # CAS claim affects zero rows -> concurrent change.
    respx_mock.patch(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())
    assert resp.status_code == 409
    assert "concurrently" in resp.json()["detail"]


def test_schedule_404_requisition_not_found(unauthed_client, cal_intel_settings, respx_mock):
    # detection select OK, CAS claim OK (1 row), but requisition missing -> 404
    # and the except-block rolls the detection status back.
    respx_mock.get(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": DETECTION_ID,
                "detection_status": "detected",
                "organization_id": ORG_ID,
                "profile_id": "p1",
            }],
        )
    )
    respx_mock.patch(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(200, json=[{"id": DETECTION_ID}])
    )
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Requisition not found"


def test_schedule_400_org_mismatch(unauthed_client, cal_intel_settings, respx_mock):
    respx_mock.get(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": DETECTION_ID,
                "detection_status": "detected",
                "organization_id": ORG_ID,
                "profile_id": "p1",
            }],
        )
    )
    respx_mock.patch(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(200, json=[{"id": DETECTION_ID}])
    )
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(
            200, json=[{"id": REQ_ID, "organization_id": "different-org"}]
        )
    )
    resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())
    assert resp.status_code == 400
    assert "does not belong" in resp.json()["detail"]


def test_schedule_404_round_not_found(unauthed_client, cal_intel_settings, respx_mock):
    respx_mock.get(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": DETECTION_ID,
                "detection_status": "detected",
                "organization_id": ORG_ID,
                "profile_id": "p1",
            }],
        )
    )
    respx_mock.patch(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(200, json=[{"id": DETECTION_ID}])
    )
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[{"id": REQ_ID, "organization_id": ORG_ID}])
    )
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Round not found"


# ---------------------------------------------------------------------------
# happy path — existing candidate, existing pending round, bot present
# ---------------------------------------------------------------------------


def _mock_common_setup(respx_mock, detection_status="detected"):
    """detection select + CAS claim + requisition + round, the shared prefix of
    every full-run test."""
    respx_mock.get(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": DETECTION_ID,
                "detection_status": detection_status,
                "organization_id": ORG_ID,
                "profile_id": "p1",
            }],
        )
    )
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[{"id": REQ_ID, "organization_id": ORG_ID}])
    )
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": ROUND_ID, "round_number": 1, "requisition_id": REQ_ID}],
        )
    )


def test_schedule_happy_path_existing_candidate_and_round(unauthed_client, cal_intel_settings, respx_mock):
    _mock_common_setup(respx_mock)
    # CAS claim then final confirm both PATCH calendar_event_detections.
    respx_mock.patch(rest_url("calendar_event_detections")).mock(
        side_effect=_seq(
            httpx.Response(200, json=[{"id": DETECTION_ID}]),  # CAS claim won
            httpx.Response(200, json=[{"id": DETECTION_ID}]),  # final confirm won
        )
    )
    # Candidate already exists for this req+email.
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ID}])
    )
    # Existing candidate_round in 'pending' -> updated to scheduled.
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": CANDIDATE_ROUND_ID,
                "status": "pending",
                "meeting_url": None,
                "scheduled_at": None,
            }],
        )
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ROUND_ID}])
    )
    # No bot bound to this detection, and meeting_url+scheduled_at present.
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[])
    )

    # The no-bot branch calls schedule_or_replace_recall_bot — patch it out.
    import app.services.recall_service as recall_service

    async def _fake_schedule(**kwargs):
        return {"ok": True}

    with _patched(recall_service, "schedule_or_replace_recall_bot", _fake_schedule):
        resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())

    assert resp.status_code == 200
    body = resp.json()
    assert body["candidate_id"] == CANDIDATE_ID
    assert body["candidate_round_id"] == CANDIDATE_ROUND_ID
    assert body["candidate_was_created"] is False
    assert body["detection_status"] == "confirmed"


def test_schedule_409_existing_round_in_progress(unauthed_client, cal_intel_settings, respx_mock):
    _mock_common_setup(respx_mock)
    respx_mock.patch(rest_url("calendar_event_detections")).mock(
        return_value=httpx.Response(200, json=[{"id": DETECTION_ID}])
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ID}])
    )
    # Existing round is completed -> cannot reuse -> 409 (rolls detection back).
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[{"id": CANDIDATE_ROUND_ID, "status": "completed"}]
        )
    )
    resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())
    assert resp.status_code == 409
    assert "cannot reuse" in resp.json()["detail"]


def test_schedule_creates_candidate_and_round_with_bot_link(unauthed_client, cal_intel_settings, respx_mock, monkeypatch):
    _mock_common_setup(respx_mock)
    respx_mock.patch(rest_url("calendar_event_detections")).mock(
        side_effect=_seq(
            httpx.Response(200, json=[{"id": DETECTION_ID}]),  # claim
            httpx.Response(200, json=[{"id": DETECTION_ID}]),  # confirm
        )
    )
    # No existing candidate -> add_candidate creates one.
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[])
    )
    new_cr_id = "00000000-0000-0000-0000-0000000000d0"

    import app.api.v2.routers.internal_calendar_intelligence as cal_router

    class _FakeCandidateService:
        async def add_candidate(self, **kwargs):
            return {"candidate": {"id": CANDIDATE_ID}}

    monkeypatch.setattr(
        "app.services.candidate_service.get_candidate_service",
        lambda: _FakeCandidateService(),
    )

    # No existing candidate_round -> INSERT a new one.
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.post(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(201, json=[{"id": new_cr_id}])
    )
    # A bot IS bound to this detection (transcript not ready) -> link only.
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": "bot-1",
                "recall_bot_id": "ext-1",
                "recording_url": None,
                "transcript_url": None,
                "transcript_ready": False,
            }],
        )
    )
    respx_mock.patch(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{"id": "bot-1"}])
    )

    resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())

    assert resp.status_code == 200
    body = resp.json()
    assert body["candidate_id"] == CANDIDATE_ID
    assert body["candidate_round_id"] == new_cr_id
    assert body["candidate_was_created"] is True


def test_schedule_links_ready_transcript_and_triggers_feedback(unauthed_client, cal_intel_settings, respx_mock, monkeypatch):
    """Bot bound to detection with a READY transcript -> the handler fetches the
    transcript, upserts it, and triggers feedback processing."""
    _mock_common_setup(respx_mock)
    respx_mock.patch(rest_url("calendar_event_detections")).mock(
        side_effect=_seq(
            httpx.Response(200, json=[{"id": DETECTION_ID}]),
            httpx.Response(200, json=[{"id": DETECTION_ID}]),
        )
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ID}])
    )
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": CANDIDATE_ROUND_ID, "status": "scheduled", "meeting_url": None, "scheduled_at": None}],
        )
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ROUND_ID}])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": "bot-9",
                "recall_bot_id": "ext-9",
                "recording_url": None,
                "transcript_url": "https://recall.example/transcript.json",
                "transcript_ready": True,
            }],
        )
    )
    respx_mock.patch(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{"id": "bot-9"}])
    )
    # The transcript fetch is a plain httpx GET to the recall URL (not Supabase).
    respx_mock.get("https://recall.example/transcript.json").mock(
        return_value=httpx.Response(200, json=[{"words": []}])
    )
    respx_mock.post(rest_url("transcripts")).mock(
        return_value=httpx.Response(201, json=[{"id": "t-1"}])
    )

    import app.services.feedback_job_service as fjs

    triggered = {}

    class _FakeFeedbackSvc:
        async def trigger_feedback_processing(self, cr_id):
            triggered["cr"] = cr_id
            return {"status": "accepted"}

    monkeypatch.setattr(fjs, "get_feedback_job_service", lambda: _FakeFeedbackSvc())

    resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())

    assert resp.status_code == 200
    assert resp.json()["detection_status"] == "confirmed"
    assert triggered["cr"] == CANDIDATE_ROUND_ID


def test_schedule_candidate_create_conflict_rechecks_and_reuses(unauthed_client, cal_intel_settings, respx_mock, monkeypatch):
    """add_candidate raises 'already exists' (race) -> handler re-queries and
    reuses the now-visible candidate rather than failing."""
    _mock_common_setup(respx_mock)
    respx_mock.patch(rest_url("calendar_event_detections")).mock(
        side_effect=_seq(
            httpx.Response(200, json=[{"id": DETECTION_ID}]),
            httpx.Response(200, json=[{"id": DETECTION_ID}]),
        )
    )
    # First candidates GET (existence check) -> empty; second GET (re-check after
    # the 'already exists' ValueError) -> found.
    respx_mock.get(rest_url("candidates")).mock(
        side_effect=_seq(
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[{"id": CANDIDATE_ID}]),
        )
    )

    class _ConflictingCandidateService:
        async def add_candidate(self, **kwargs):
            raise ValueError("A candidate with email ... already exists for this requisition")

    monkeypatch.setattr(
        "app.services.candidate_service.get_candidate_service",
        lambda: _ConflictingCandidateService(),
    )

    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": CANDIDATE_ROUND_ID, "status": "pending", "meeting_url": None, "scheduled_at": None}],
        )
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ROUND_ID}])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[])
    )

    import app.services.recall_service as recall_service

    async def _fake_schedule(**kwargs):
        return {"ok": True}

    with _patched(recall_service, "schedule_or_replace_recall_bot", _fake_schedule):
        resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())

    assert resp.status_code == 200
    body = resp.json()
    assert body["candidate_id"] == CANDIDATE_ID
    # Reused an existing candidate -> not created.
    assert body["candidate_was_created"] is False


# ---------------------------------------------------------------------------
# backfill endpoint
# ---------------------------------------------------------------------------


def test_backfill_403_without_secret(unauthed_client):
    resp = unauthed_client.post("/api/v2/internal/calendar-intelligence/backfill", json={})
    assert resp.status_code == 403


def test_backfill_happy_path(unauthed_client, cal_intel_settings, monkeypatch):
    import app.services.google_calendar_service as gcs

    class _FakeGcalService:
        async def backfill_recall_registrations(self):
            return {"registered": 3}

    monkeypatch.setattr(gcs, "get_google_calendar_service", lambda: _FakeGcalService())

    resp = unauthed_client.post(
        "/api/v2/internal/calendar-intelligence/backfill",
        headers=_headers(),
        json={},
    )
    assert resp.status_code == 200
    assert resp.json() == {"registered": 3}


# ---------------------------------------------------------------------------
# rollback — final CAS confirm loses the race (compensating teardown)
# ---------------------------------------------------------------------------


def test_schedule_rollback_when_final_confirm_loses_race(unauthed_client, cal_intel_settings, respx_mock):
    """A new candidate_round was inserted, but the final CAS confirm matched zero
    rows. The handler must (a) cancel the freshly-created round and (b) return
    409. We assert the 409 and that a follow-up PATCH to candidate_rounds (the
    cancellation) occurred."""
    _mock_common_setup(respx_mock)
    respx_mock.patch(rest_url("calendar_event_detections")).mock(
        side_effect=_seq(
            httpx.Response(200, json=[{"id": DETECTION_ID}]),  # claim won
            httpx.Response(200, json=[]),                       # final confirm LOST
            # The 409 raised by _execute_schedule bubbles to the outer try/except
            # in schedule_from_detection, which rolls the detection back to its
            # original status with one more PATCH.
            httpx.Response(200, json=[{"id": DETECTION_ID}]),  # outer rollback
        )
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ID}])
    )
    new_cr_id = "00000000-0000-0000-0000-0000000000d1"
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.post(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(201, json=[{"id": new_cr_id}])
    )
    cr_patch = respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{"id": new_cr_id}])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[])
    )

    # No bot, but meeting_url+scheduled_at present -> schedule bot (patched).
    import app.services.recall_service as recall_service

    async def _fake_schedule(**kwargs):
        return {"ok": True}

    with _patched(recall_service, "schedule_or_replace_recall_bot", _fake_schedule):
        resp = unauthed_client.post(SCHEDULE_PATH, headers=_headers(), json=_body())

    assert resp.status_code == 409
    assert "state changed during processing" in resp.json()["detail"]
    # The compensating rollback cancelled the just-created round.
    assert cr_patch.called


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------


class _patched:
    """Tiny context manager to monkeypatch a module attr without the pytest
    fixture (so it can be used inside a `with` in a plain test body)."""

    def __init__(self, module, name, value):
        self._module = module
        self._name = name
        self._value = value
        self._orig = getattr(module, name)

    def __enter__(self):
        setattr(self._module, self._name, self._value)
        return self

    def __exit__(self, *exc):
        setattr(self._module, self._name, self._orig)
        return False
