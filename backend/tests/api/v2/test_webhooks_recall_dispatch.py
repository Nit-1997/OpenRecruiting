"""Dispatch + branch tests for the recall webhook router (webhooks.py).

ENV=test + no webhook-signature header → _verify_or_test_bypass returns True,
so the handler body runs. Covers the realtime event routing (join/leave/chat/
transcript/unhandled/missing-bot), the main webhook bot_status_change ignored
branch, and unhandled main events.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v2.routers import webhooks as wh

V2 = "/api/v2"


# ------------- account webhook (/webhooks/recall/bot-status) -------------

def test_main_bot_status_unmapped_ignored(unauthed_client):
    with patch.object(wh.bot_status_handler, "handle_bot_status_change", AsyncMock(return_value=None)), \
         patch.object(wh, "_supabase", lambda: MagicMock()):
        resp = unauthed_client.post(f"{V2}/webhooks/recall/bot-status", json={
            "event": "bot.status_change", "data": {"bot_id": "b1", "status": {"code": "x"}},
        })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_main_bot_status_ok(unauthed_client):
    outcome = wh.bot_status_handler.BotStatusOutcome(
        bot_id="b1", db_status="done", transitioned_cr=True,
        not_admitted_enqueued=False, recording_fetch_enqueued=True,
    )
    with patch.object(wh.bot_status_handler, "handle_bot_status_change", AsyncMock(return_value=outcome)), \
         patch.object(wh, "_supabase", lambda: MagicMock()):
        resp = unauthed_client.post(f"{V2}/webhooks/recall/bot-status", json={
            "event": "bot.status_change", "data": {"bot_id": "b1", "status": {"code": "done"}},
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["new_status"] == "done"
    assert body["recording_fetch_queued"] is True


def test_main_unhandled_event_ignored(unauthed_client):
    resp = unauthed_client.post(f"{V2}/webhooks/recall/bot-status", json={"event": "something.else", "data": {}})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


# --------------- granular bot.* events (Recall's real format) ---------------
# Regression guard for the v1->v2 port bug: Recall fires GRANULAR bot lifecycle
# events (bot.joining_call / bot.in_call_recording / bot.done / bot.fatal), each
# a distinct event type with the bot id at data.bot.id — NOT a single
# bot.status_change with data.status.code. v1 handled these
# (legacy .../api/v1/webhooks/recall.py:340-352); the v2 port matched only
# "bot.status_change", so every real event fell through to "unhandled" and the
# whole post-interview pipeline (recording/feedback/packet/reminder) silently
# never ran. Mirrors legacy tests/test_webhooks_recall*.

@pytest.mark.parametrize("event,code", [
    ("bot.joining_call", "joining_call"),
    ("bot.in_call_recording", "in_call_recording"),
    ("bot.done", "done"),
    ("bot.fatal", "fatal"),
])
def test_granular_bot_event_normalized_and_dispatched(unauthed_client, event, code):
    outcome = wh.bot_status_handler.BotStatusOutcome(
        bot_id="ext-123", db_status=code, transitioned_cr=False,
        not_admitted_enqueued=False, recording_fetch_enqueued=(code == "done"),
    )
    mock = AsyncMock(return_value=outcome)
    with patch.object(wh.bot_status_handler, "handle_bot_status_change", mock), \
         patch.object(wh, "_supabase", lambda: MagicMock()):
        resp = unauthed_client.post(f"{V2}/webhooks/recall/bot-status", json={
            "event": event,
            "data": {"bot": {"id": "ext-123"}, "data": {"sub_code": "sc"}},
        })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    # The handler MUST receive the normalized shape: bot_id from data.bot.id and
    # status.code derived from the event NAME (not from a data.status.code that
    # granular events don't carry).
    _supabase_arg, payload_data, _bg = mock.await_args.args
    assert payload_data["bot_id"] == "ext-123"
    assert payload_data["status"] == {"code": code, "sub_code": "sc"}


def test_granular_bot_done_queues_recording_fetch(unauthed_client):
    outcome = wh.bot_status_handler.BotStatusOutcome(
        bot_id="ext-123", db_status="done", transitioned_cr=False,
        not_admitted_enqueued=False, recording_fetch_enqueued=True,
    )
    with patch.object(wh.bot_status_handler, "handle_bot_status_change", AsyncMock(return_value=outcome)), \
         patch.object(wh, "_supabase", lambda: MagicMock()):
        resp = unauthed_client.post(f"{V2}/webhooks/recall/bot-status", json={
            "event": "bot.done", "data": {"bot": {"id": "ext-123"}},
        })
    body = resp.json()
    assert body["status"] == "ok"
    assert body["new_status"] == "done"
    assert body["recording_fetch_queued"] is True


def test_granular_bot_event_bot_id_fallback_to_flat(unauthed_client):
    # Tolerate a flat data.bot_id (some payloads) as well as nested data.bot.id.
    outcome = wh.bot_status_handler.BotStatusOutcome(
        bot_id="flat-1", db_status="in_call_recording", transitioned_cr=True,
        not_admitted_enqueued=False, recording_fetch_enqueued=False,
    )
    mock = AsyncMock(return_value=outcome)
    with patch.object(wh.bot_status_handler, "handle_bot_status_change", mock), \
         patch.object(wh, "_supabase", lambda: MagicMock()):
        resp = unauthed_client.post(f"{V2}/webhooks/recall/bot-status", json={
            "event": "bot.in_call_recording", "data": {"bot_id": "flat-1"},
        })
    assert resp.status_code == 200
    assert mock.await_args.args[1]["bot_id"] == "flat-1"


# ----------------------- realtime webhook -----------------------

def test_realtime_missing_bot_id(unauthed_client):
    resp = unauthed_client.post(f"{V2}/webhooks/recall/realtime", json={
        "event": "participant_events.join", "data": {},
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"


def test_realtime_participant_join_dispatch(unauthed_client):
    with patch.object(wh.participant_handler, "handle_participant_join", AsyncMock()) as h:
        resp = unauthed_client.post(f"{V2}/webhooks/recall/realtime", json={
            "event": "participant_events.join", "data": {"bot": {"id": "b1"}},
        })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    h.assert_awaited_once()


def test_realtime_participant_leave_dispatch(unauthed_client):
    with patch.object(wh.participant_handler, "handle_participant_leave", AsyncMock()) as h:
        resp = unauthed_client.post(f"{V2}/webhooks/recall/realtime", json={
            "event": "participant_events.leave", "data": {"bot": {"id": "b1"}},
        })
    assert resp.status_code == 200
    h.assert_awaited_once()


def test_realtime_chat_dispatch(unauthed_client):
    with patch.object(wh.chat_handler, "handle_chat_message", AsyncMock()) as h:
        resp = unauthed_client.post(f"{V2}/webhooks/recall/realtime", json={
            "event": "participant_events.chat_message", "data": {"bot": {"id": "b1"}},
        })
    assert resp.status_code == 200
    h.assert_awaited_once()


def test_realtime_transcript_dispatch(unauthed_client):
    with patch.object(wh.transcript_handler, "handle_transcript_data", AsyncMock()) as h:
        resp = unauthed_client.post(f"{V2}/webhooks/recall/realtime", json={
            "event": "transcript.data", "data": {"bot": {"id": "b1"}},
        })
    assert resp.status_code == 200
    h.assert_awaited_once()


def test_realtime_unhandled_event_ignored(unauthed_client):
    resp = unauthed_client.post(f"{V2}/webhooks/recall/realtime", json={
        "event": "weird.event", "data": {"bot": {"id": "b1"}},
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


# ----------------------- _looks_like_production -----------------------

def test_looks_like_production():
    """Fail-closed: anything that is not a recognised local/tunnel host counts
    as production, so the ENV=test HMAC bypass stays unreachable there."""
    from types import SimpleNamespace

    def looks_prod(url):
        return wh._looks_like_production(SimpleNamespace(WEBHOOK_BASE_URL=url))

    # Self-hosters serve webhooks from their own domain -> treat as production.
    assert looks_prod("https://hooks.acme-corp.example") is True
    # Unset is production too, never a licence to bypass.
    assert looks_prod(None) is True
    assert looks_prod("") is True

    # Recognised development hosts.
    assert looks_prod("http://localhost:8004") is False
    assert looks_prod("http://127.0.0.1:8004") is False
    assert looks_prod("http://host.docker.internal:8004") is False
    assert looks_prod("https://abc123.ngrok-free.app") is False
    assert looks_prod("https://demo.trycloudflare.com") is False
