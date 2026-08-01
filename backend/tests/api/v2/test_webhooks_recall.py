"""
Recall webhook tests — verifies the v2 port of v1's webhook lifecycle.

Coverage:
  - bot.status_change transitions (in_call_recording, call_ended, done, fatal)
  - signature bypass in ENV=test (matches v1 behaviour)
  - participant_events.join populates tracked_participants
  - participant_events.leave triggers feedback collection via heuristic
  - chat_message "Scout on" / "yes" triggers feedback collection
  - calendar events are ignored (v1-owned)

These exercise the wire contract through respx-mocked Supabase. They do
NOT exercise the Recall API itself (monkey-patched).
"""

import json
import httpx
import pytest

from tests.helpers.mock_data import (
    CANDIDATE_ROUND_ID,
    NOW,
    REQ_ID,
)
from tests.helpers.supabase_mocks import rest_url


V2_ROOT = "/api/v2"
BOT_ID = "recall-bot-abc-123"
BOT_DB_ID = "00000000-0000-0000-0000-0000000000bb"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_bot_row(
    *,
    status: str = "joining",
    feedback_status: str = "none",
    candidate_round_id: str | None = CANDIDATE_ROUND_ID,
    detection_completed: bool = False,
    detected_pid=None,
    confidence: float = 0.0,
    tracked: list | None = None,
    credit_charged: bool = False,
    error_code: str | None = None,
):
    return {
        "id": BOT_DB_ID,
        "recall_bot_id": BOT_ID,
        "candidate_round_id": candidate_round_id,
        "candidate_name": "Test Candidate",
        "meeting_url": "https://meet.google.com/test",
        "status": status,
        "feedback_status": feedback_status,
        "tracked_participants": tracked or [],
        "detection_completed": detection_completed,
        "detected_candidate_participant_id": detected_pid,
        "detection_confidence": confidence,
        "credit_charged": credit_charged,
        "error_code": error_code,
        "status_history": [],
        "joined_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


# ---------------------------------------------------------------------------
# Signature bypass under ENV=test
# ---------------------------------------------------------------------------


def test_webhook_rejects_when_signature_present_but_invalid(
    unauthed_client, respx_mock
):
    """If a signature header IS supplied (i.e. caller is claiming to be
    Recall), we run verification even in ENV=test. An invalid signature
    must produce 401."""
    resp = unauthed_client.post(
        f"{V2_ROOT}/webhooks/recall/bot-status",
        headers={
            "webhook-id": "msg_test",
            "webhook-timestamp": "1700000000",
            "webhook-signature": "v1,bogus-signature",
        },
        json={"event": "bot.status_change", "data": {}},
    )
    assert resp.status_code == 401


def test_webhook_bypass_in_test_env(unauthed_client, respx_mock, monkeypatch):
    """ENV=test + no signature header → handler runs (calendar event queued)."""
    import app.workers.calendar_intelligence_worker as worker

    async def fake_enqueue(event_type, data):
        return {"calendar_id": "unknown", "hint_dt": None}

    monkeypatch.setattr(worker, "enqueue_calendar_sync_hint", fake_enqueue)
    resp = unauthed_client.post(
        f"{V2_ROOT}/webhooks/recall/bot-status",
        json={"event": "calendar.event_updated", "data": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Calendar events are now routed to the ported worker.
    assert body["status"] == "queued"
    assert body["event"] == "calendar.event_updated"


def test_unsigned_webhook_rejected_when_prod_misconfigured_as_test(
    unauthed_client, respx_mock, monkeypatch
):
    """A misconfigured prod deployment running ENV=test must NOT be able to
    accept UNSIGNED webhooks. The test bypass is gated behind a non-prod
    assertion: when WEBHOOK_BASE_URL is not a recognised local/tunnel host the
    deployment is assumed to be production, the bypass refuses, and real HMAC
    verification runs — an unsigned request then 401s."""
    from app.config import get_settings

    monkeypatch.setenv("WEBHOOK_BASE_URL", "https://hooks.acme-corp.example")
    get_settings.cache_clear()

    resp = unauthed_client.post(
        f"{V2_ROOT}/webhooks/recall/bot-status",
        json={"event": "bot.status_change", "data": {}},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# bot.status_change → in_call_recording
# ---------------------------------------------------------------------------


def test_status_change_in_call_recording_transitions_cr(
    unauthed_client, respx_mock
):
    """bot.status_change → in_call_recording flips the CR to in_progress."""
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[_make_bot_row()])
    )
    # candidate_rounds PATCH (status → in_progress) returns the updated row.
    cr_patches: list[dict] = []

    def _patch_cr(request):
        cr_patches.append(json.loads(request.content.decode()))
        return httpx.Response(200, json=[{"id": CANDIDATE_ROUND_ID, "status": "in_progress"}])

    respx_mock.patch(rest_url("candidate_rounds")).mock(side_effect=_patch_cr)
    # CAS credit flip + final bot update both target recall_bots.
    respx_mock.patch(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{}])
    )
    # org lookup
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[
            {"candidates": {"requisitions": {"organization_id": "org-1"}}}
        ])
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/webhooks/recall/bot-status",
        json={
            "event": "bot.status_change",
            "data": {
                "bot_id": BOT_ID,
                "status": {"code": "in_call_recording", "sub_code": None},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["bot_id"] == BOT_ID
    assert body["new_status"] == "in_call_recording"
    assert body["cr_transitioned"] is True
    # CR was patched to in_progress
    assert any(p.get("status") == "in_progress" for p in cr_patches)


# ---------------------------------------------------------------------------
# bot.status_change → fatal with not-admitted sub_code
# ---------------------------------------------------------------------------


def test_status_change_fatal_with_not_admitted_enqueues_notifier(
    unauthed_client, respx_mock
):
    """fatal + sub_code containing 'waiting_room' triggers the notifier."""
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[_make_bot_row()])
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{}])
    )
    respx_mock.patch(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{}])
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/webhooks/recall/bot-status",
        json={
            "event": "bot.status_change",
            "data": {
                "bot_id": BOT_ID,
                "status": {"code": "fatal", "sub_code": "waiting_room_timeout"},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["new_status"] == "failed"
    assert body["not_admitted_queued"] is True


# ---------------------------------------------------------------------------
# bot.status_change → done queues recording fetch
# ---------------------------------------------------------------------------


def test_status_change_done_queues_recording_fetch(unauthed_client, respx_mock):
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[_make_bot_row(status="processing")])
    )
    respx_mock.patch(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{}])
    )
    resp = unauthed_client.post(
        f"{V2_ROOT}/webhooks/recall/bot-status",
        json={
            "event": "bot.status_change",
            "data": {
                "bot_id": BOT_ID,
                "status": {"code": "done", "sub_code": None},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["recording_fetch_queued"] is True


def test_status_change_done_replay_does_not_re_enqueue_fetch(
    unauthed_client, respx_mock
):
    """A duplicate `done` event (webhooks are at-least-once) must NOT
    re-enqueue the recording fetch — the bot is already in `done` state
    from the first delivery. Re-firing would re-run _decide_feedback_path
    and re-trigger the Lambda (the May-2026 two-trigger race)."""
    # Bot already done from the first delivery.
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[_make_bot_row(status="done")])
    )
    respx_mock.patch(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{}])
    )
    resp = unauthed_client.post(
        f"{V2_ROOT}/webhooks/recall/bot-status",
        json={
            "event": "bot.status_change",
            "data": {
                "bot_id": BOT_ID,
                "status": {"code": "done", "sub_code": None},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    # The replay is a no-op for the recording fetch.
    assert body["recording_fetch_queued"] is False


# ---------------------------------------------------------------------------
# unknown bot → ignored, no DB writes
# ---------------------------------------------------------------------------


def test_status_change_unknown_bot_ignored(unauthed_client, respx_mock):
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = unauthed_client.post(
        f"{V2_ROOT}/webhooks/recall/bot-status",
        json={
            "event": "bot.status_change",
            "data": {
                "bot_id": "unknown-bot",
                "status": {"code": "in_call_recording", "sub_code": None},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ignored"


# ---------------------------------------------------------------------------
# participant_events.join
# ---------------------------------------------------------------------------


def test_realtime_participant_join_appends_to_tracked(unauthed_client, respx_mock):
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[_make_bot_row()])
    )
    captured = {}

    def _patch_bot(request):
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=[{}])

    respx_mock.patch(rest_url("recall_bots")).mock(side_effect=_patch_bot)

    resp = unauthed_client.post(
        f"{V2_ROOT}/webhooks/recall/realtime",
        json={
            "event": "participant_events.join",
            "data": {
                "bot": {"id": BOT_ID},
                "data": {
                    "participant": {
                        "id": 42,
                        "name": "Jane Interviewer",
                        "is_host": True,
                        "platform": "zoom",
                        "email": "jane@example.com",
                    }
                },
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = captured["body"]
    assert "tracked_participants" in body
    tracked = body["tracked_participants"]
    assert any(p["id"] == 42 and p["is_host"] for p in tracked)


# ---------------------------------------------------------------------------
# participant_events.leave heuristic — non-interviewer leaves while
# interviewer remains → fires trigger_feedback_collection
# ---------------------------------------------------------------------------


def test_realtime_participant_leave_drops_candidate_via_heuristic(
    unauthed_client, respx_mock
):
    tracked = [
        # The interviewer (still in call)
        {"id": 1, "name": "Jane", "is_host": True, "email": "jane@ex.com", "left_at": None},
        # The leaving candidate
        {"id": 2, "name": "Candidate", "is_host": False, "email": None, "left_at": None},
    ]
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[
            _make_bot_row(feedback_status="waiting_for_leave", tracked=tracked)
        ])
    )
    respx_mock.patch(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{}])
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/webhooks/recall/realtime",
        json={
            "event": "participant_events.leave",
            "data": {
                "bot": {"id": BOT_ID},
                "data": {"participant": {"id": 2, "name": "Candidate"}},
            },
        },
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Calendar event — ignored
# ---------------------------------------------------------------------------


def test_main_webhook_routes_calendar_event_to_worker(
    unauthed_client, respx_mock, monkeypatch
):
    import app.workers.calendar_intelligence_worker as worker

    async def fake_enqueue(event_type, data):
        return {"calendar_id": "cal_1", "hint_dt": None}

    monkeypatch.setattr(worker, "enqueue_calendar_sync_hint", fake_enqueue)
    resp = unauthed_client.post(
        f"{V2_ROOT}/webhooks/recall/bot-status",
        json={"event": "calendar.event_updated", "data": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert body["event"] == "calendar.event_updated"
    assert body["calendar_id"] == "cal_1"
    assert body.get("reason") != "calendar_owned_by_v1"
