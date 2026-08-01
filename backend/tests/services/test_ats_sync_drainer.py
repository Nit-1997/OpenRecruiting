"""drain_once: oldest-first batch, per-event isolation, retry/park semantics.
Parking = processed_at set WITH the error retained once retry_count reaches
ATS_SYNC_MAX_RETRIES (keeps the pending fetch starvation-free without needing
range filters on the client)."""

import json

from tests.helpers.supabase_mocks import mock_select, mock_update

from app.services.ats_sync import drainer
from app.services.ats_sync.handlers import EventOutcome
from app.services.supabase import get_supabase_admin_client


def pending_row(event_id, retry_count=0):
    return {
        "event_id": event_id,
        "event_type": "record.new",
        "integration_id": "int-1",
        "payload": {"eventType": "record.new", "syncDataType": "ats_jobs"},
        "retry_count": retry_count,
    }


def fake_outcomes(monkeypatch, outcomes: dict):
    async def _fake_apply(_supabase, row):
        result = outcomes[row["event_id"]]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(drainer, "apply_event", _fake_apply)


async def test_applied_events_marked_processed(respx_mock, monkeypatch):
    mock_select(respx_mock, "ats_webhook_events", [pending_row("e1"), pending_row("e2")])
    update_route = mock_update(respx_mock, "ats_webhook_events")
    fake_outcomes(
        monkeypatch,
        {"e1": EventOutcome("applied"), "e2": EventOutcome("bookkeeping")},
    )
    handled = await drainer.drain_once(get_supabase_admin_client())
    assert handled == 2
    assert update_route.call_count == 2
    first_update = json.loads(update_route.calls[0].request.content)
    assert first_update["processed_at"] is not None


async def test_failed_event_retries_without_processing(respx_mock, monkeypatch):
    mock_select(respx_mock, "ats_webhook_events", [pending_row("e1", retry_count=0)])
    update_route = mock_update(respx_mock, "ats_webhook_events")
    fake_outcomes(monkeypatch, {"e1": EventOutcome("failed", "boom")})
    handled = await drainer.drain_once(get_supabase_admin_client())
    assert handled == 0
    sent = json.loads(update_route.calls[0].request.content)
    assert sent["retry_count"] == 1
    assert sent["processing_error"] == "boom"
    assert "processed_at" not in sent


async def test_exhausted_retries_park_with_processed_at(respx_mock, monkeypatch):
    # retry_count 4 + this failure = 5 (== ATS_SYNC_MAX_RETRIES) → parked.
    mock_select(respx_mock, "ats_webhook_events", [pending_row("e1", retry_count=4)])
    update_route = mock_update(respx_mock, "ats_webhook_events")
    fake_outcomes(monkeypatch, {"e1": EventOutcome("orphaned", "no job link")})
    handled = await drainer.drain_once(get_supabase_admin_client())
    assert handled == 0
    sent = json.loads(update_route.calls[0].request.content)
    assert sent["retry_count"] == 5
    assert sent["processed_at"] is not None
    assert sent["processing_error"] == "no job link"


async def test_handler_exception_is_isolated(respx_mock, monkeypatch):
    mock_select(
        respx_mock, "ats_webhook_events", [pending_row("e1"), pending_row("e2")]
    )
    update_route = mock_update(respx_mock, "ats_webhook_events")
    fake_outcomes(
        monkeypatch,
        {"e1": RuntimeError("kaboom"), "e2": EventOutcome("applied")},
    )
    handled = await drainer.drain_once(get_supabase_admin_client())
    assert handled == 1
    assert update_route.call_count == 2  # retry update for e1 + processed for e2


async def test_empty_batch_returns_zero(respx_mock):
    mock_select(respx_mock, "ats_webhook_events", [])
    assert await drainer.drain_once(get_supabase_admin_client()) == 0
