"""Unit tests for GoogleCalendarService (BE-T7 coverage).

Complements test_google_calendar_retry.py (which covers the 429/5xx backoff).
Here we cover the happy/error bodies of exchange_code, get_userinfo,
_get_valid_token (cached + refresh-write), get_connection, save_connection,
register_with_recall, disconnect, find_available_slots, create_meet_event,
create_calendar_event, build_oauth_url, the Fernet crypto + oauth-state, and
backfill_recall_registrations.

HTTP is mocked via get_async_http_client; Supabase via respx; the standalone
_send_with_backoff helpers are also covered for completeness.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

from app.services import google_calendar_service as gcs
from app.services.google_calendar_service import (
    GoogleCalendarService,
    _backoff_delay,
    _is_retryable_status,
    _retry_after_seconds,
    _strip_offset,
    get_google_calendar_service,
)
from tests.helpers.supabase_mocks import rest_url

FERNET_KEY = Fernet.generate_key().decode()


def _make_service(monkeypatch) -> GoogleCalendarService:
    settings = gcs.get_settings()
    monkeypatch.setattr(settings, "INTEGRATION_ENCRYPTION_KEY", FERNET_KEY, raising=False)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid", raising=False)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "csec", raising=False)
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "https://app/cb", raising=False)
    return GoogleCalendarService()


def _resp(status: int, json_body=None, headers=None, text: str = ""):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else {}
    r.text = text
    r.headers = headers or {}
    return r


# --------------------------------------------------------------------------
# Module-level helpers
# --------------------------------------------------------------------------

def test_is_retryable_status():
    assert _is_retryable_status(429) is True
    assert _is_retryable_status(500) is True
    assert _is_retryable_status(503) is True
    assert _is_retryable_status(401) is False
    assert _is_retryable_status(200) is False


def test_retry_after_seconds_parses_and_handles_garbage():
    assert _retry_after_seconds(_resp(429, headers={"Retry-After": "5"})) == 5.0
    assert _retry_after_seconds(_resp(429, headers={"Retry-After": "abc"})) is None
    assert _retry_after_seconds(_resp(429, headers={})) is None
    assert _retry_after_seconds(None) is None


def test_backoff_delay_honors_retry_after_and_exp():
    # Retry-After wins, capped at max.
    assert _backoff_delay(0, _resp(429, headers={"Retry-After": "100"})) == gcs.RETRY_MAX_BACKOFF_SECONDS
    # No header → exponential with jitter, within bounds.
    d = _backoff_delay(1, _resp(500, headers={}))
    assert gcs.RETRY_BASE_SECONDS * 2 <= d <= gcs.RETRY_BASE_SECONDS * 2 + gcs.RETRY_JITTER_SECONDS


def test_strip_offset():
    assert _strip_offset("2030-01-01T10:00:00+05:30") == "2030-01-01T10:00:00"
    assert _strip_offset("2030-01-01T10:00:00Z") == "2030-01-01T10:00:00"
    assert _strip_offset("2030-01-01T10:00:00") == "2030-01-01T10:00:00"


# --------------------------------------------------------------------------
# Crypto + oauth-state
# --------------------------------------------------------------------------

def test_encrypt_decrypt_round_trip(monkeypatch):
    svc = _make_service(monkeypatch)
    enc = svc.encrypt_token("ya29.token")
    assert enc != "ya29.token"
    assert svc.decrypt_token(enc) == "ya29.token"


def test_crypto_without_key_raises():
    svc = GoogleCalendarService()
    assert svc._fernet is None
    with pytest.raises(RuntimeError):
        svc.encrypt_token("x")
    with pytest.raises(RuntimeError):
        svc.decrypt_token("x")
    with pytest.raises(RuntimeError):
        svc.create_oauth_state("u", "o")
    with pytest.raises(RuntimeError):
        svc.verify_oauth_state("s")


def test_oauth_state_round_trip_and_expiry(monkeypatch):
    svc = _make_service(monkeypatch)
    state = svc.create_oauth_state("u1", "o1")
    data = svc.verify_oauth_state(state)
    assert data["user_id"] == "u1" and data["org_id"] == "o1"

    expired = svc._fernet.encrypt(
        json.dumps({"user_id": "u", "org_id": "o", "exp": int(time.time()) - 1}).encode()
    ).decode()
    with pytest.raises(ValueError, match="expired"):
        svc.verify_oauth_state(expired)

    with pytest.raises(ValueError, match="Invalid OAuth state"):
        svc.verify_oauth_state("garbage")


def test_build_oauth_url(monkeypatch):
    svc = _make_service(monkeypatch)
    url = svc.build_oauth_url("the-state")
    assert url.startswith(gcs.GOOGLE_AUTH_URL)
    assert "client_id=cid" in url
    assert "state=the-state" in url
    assert "access_type=offline" in url


# --------------------------------------------------------------------------
# exchange_code / get_userinfo
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exchange_code_success(monkeypatch):
    svc = _make_service(monkeypatch)
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(200, {"access_token": "t", "refresh_token": "r"}))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    data = await svc.exchange_code("auth-code")
    assert data["access_token"] == "t"
    assert client.post.call_args.kwargs["data"]["code"] == "auth-code"


@pytest.mark.asyncio
async def test_exchange_code_failure_raises(monkeypatch):
    svc = _make_service(monkeypatch)
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(400, {"error": "invalid_grant",
                                                     "error_description": "bad code"}))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    with pytest.raises(ValueError, match="bad code"):
        await svc.exchange_code("x")


@pytest.mark.asyncio
async def test_get_userinfo_success(monkeypatch):
    svc = _make_service(monkeypatch)
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(200, {"email": "a@b.com"}))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    assert (await svc.get_userinfo("tok"))["email"] == "a@b.com"


# --------------------------------------------------------------------------
# get_connection / _get_valid_token
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_connection(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    respx_mock.get(rest_url("user_connections")).mock(
        return_value=httpx.Response(200, json=[{"id": "c1", "profile_id": "p1"}])
    )
    out = await svc.get_connection("p1")
    assert out["id"] == "c1"


@pytest.mark.asyncio
async def test_get_connection_empty(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    respx_mock.get(rest_url("user_connections")).mock(return_value=httpx.Response(200, json=[]))
    assert await svc.get_connection("p1") is None


@pytest.mark.asyncio
async def test_get_valid_token_not_connected_raises(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "get_connection", AsyncMock(return_value=None))
    with pytest.raises(ValueError, match="not connected"):
        await svc._get_valid_token("p1")


@pytest.mark.asyncio
async def test_get_valid_token_cached_when_not_expiring(monkeypatch):
    svc = _make_service(monkeypatch)
    far = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    enc = svc.encrypt_token("ya29.cached")
    monkeypatch.setattr(
        svc, "get_connection",
        AsyncMock(return_value={"id": "c1", "token_expires_at": far, "access_token_encrypted": enc}),
    )
    assert await svc._get_valid_token("p1") == "ya29.cached"


@pytest.mark.asyncio
async def test_get_valid_token_refreshes_and_persists(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    soon = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
    monkeypatch.setattr(
        svc, "get_connection",
        AsyncMock(return_value={"id": "c1", "token_expires_at": soon,
                                "access_token_encrypted": svc.encrypt_token("old"),
                                "refresh_token_encrypted": svc.encrypt_token("refresh")}),
    )
    monkeypatch.setattr(
        svc, "_refresh_token",
        AsyncMock(return_value={"access_token": "ya29.new", "expires_in": 3600, "refresh_token": "new-refresh"}),
    )
    update_route = respx_mock.patch(rest_url("user_connections")).mock(
        return_value=httpx.Response(200, json=[{"id": "c1"}])
    )
    out = await svc._get_valid_token("p1")
    assert out == "ya29.new"
    assert update_route.called


# --------------------------------------------------------------------------
# save_connection
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_connection_insert_when_new(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    respx_mock.get(rest_url("user_connections")).mock(return_value=httpx.Response(200, json=[]))
    insert_route = respx_mock.post(rest_url("user_connections")).mock(
        return_value=httpx.Response(201, json=[{"id": "c1"}])
    )
    await svc.save_connection("p1", "o1", {"access_token": "a", "refresh_token": "r", "expires_in": 3600}, "a@b.com")
    assert insert_route.called


@pytest.mark.asyncio
async def test_save_connection_updates_when_existing(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    settings = gcs.get_settings()
    monkeypatch.setattr(settings, "CALENDAR_INTELLIGENCE_ENABLED", True, raising=False)
    respx_mock.get(rest_url("user_connections")).mock(
        return_value=httpx.Response(200, json=[{"id": "c1", "recall_calendar_id": "rc-old"}])
    )
    update_route = respx_mock.patch(rest_url("user_connections")).mock(
        return_value=httpx.Response(200, json=[{"id": "c1"}])
    )
    await svc.save_connection("p1", "o1", {"access_token": "a", "refresh_token": "r"}, "a@b.com")
    assert update_route.called
    assert svc._prior_recall_calendar_id == "rc-old"


# --------------------------------------------------------------------------
# register_with_recall
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_with_recall_disabled_returns_false(monkeypatch):
    svc = _make_service(monkeypatch)
    settings = gcs.get_settings()
    monkeypatch.setattr(settings, "CALENDAR_INTELLIGENCE_ENABLED", False, raising=False)
    assert await svc.register_with_recall("p1", "o1") is False


@pytest.mark.asyncio
async def test_register_with_recall_no_connection_false(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    settings = gcs.get_settings()
    monkeypatch.setattr(settings, "CALENDAR_INTELLIGENCE_ENABLED", True, raising=False)
    respx_mock.get(rest_url("user_connections")).mock(return_value=httpx.Response(200, json=[]))
    assert await svc.register_with_recall("p1", "o1") is False


@pytest.mark.asyncio
async def test_register_with_recall_success(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    settings = gcs.get_settings()
    monkeypatch.setattr(settings, "CALENDAR_INTELLIGENCE_ENABLED", True, raising=False)
    respx_mock.get(rest_url("user_connections")).mock(
        return_value=httpx.Response(200, json=[{"refresh_token_encrypted": svc.encrypt_token("r"),
                                                "provider_email": "a@b.com"}])
    )
    recall_cal = MagicMock()
    recall_cal.register_calendar = AsyncMock(return_value="rc-123")
    recall_cal.close = AsyncMock()
    monkeypatch.setattr(
        "app.services.recall_calendar_service.get_recall_calendar_service", lambda: recall_cal
    )
    assert await svc.register_with_recall("p1", "o1") is True
    recall_cal.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_with_recall_failure_restores_prior(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    svc._prior_recall_calendar_id = "rc-prior"
    settings = gcs.get_settings()
    monkeypatch.setattr(settings, "CALENDAR_INTELLIGENCE_ENABLED", True, raising=False)
    respx_mock.get(rest_url("user_connections")).mock(
        return_value=httpx.Response(200, json=[{"refresh_token_encrypted": svc.encrypt_token("r"),
                                                "provider_email": "a@b.com"}])
    )
    restore_route = respx_mock.patch(rest_url("user_connections")).mock(
        return_value=httpx.Response(200, json=[{"id": "c1"}])
    )
    recall_cal = MagicMock()
    recall_cal.register_calendar = AsyncMock(return_value=None)
    recall_cal.close = AsyncMock()
    monkeypatch.setattr(
        "app.services.recall_calendar_service.get_recall_calendar_service", lambda: recall_cal
    )
    assert await svc.register_with_recall("p1", "o1") is False
    assert restore_route.called


# --------------------------------------------------------------------------
# disconnect
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disconnect_no_recall_calendar(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    respx_mock.get(rest_url("user_connections")).mock(
        return_value=httpx.Response(200, json=[{"recall_calendar_id": None}])
    )
    respx_mock.patch(rest_url("user_connections")).mock(return_value=httpx.Response(200, json=[{"id": "c1"}]))
    out = await svc.disconnect("p1")
    assert out == {"disconnected": True, "recall_deregistered": False}


@pytest.mark.asyncio
async def test_disconnect_deregisters_recall(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    respx_mock.get(rest_url("user_connections")).mock(
        return_value=httpx.Response(200, json=[{"recall_calendar_id": "rc-1"}])
    )
    respx_mock.patch(rest_url("user_connections")).mock(return_value=httpx.Response(200, json=[{"id": "c1"}]))

    recall_cal = MagicMock()
    recall_cal.client = MagicMock()
    recall_cal.client.delete = AsyncMock(return_value=_resp(204))
    recall_cal.close = AsyncMock()
    monkeypatch.setattr(
        "app.services.recall_calendar_service.get_recall_calendar_service", lambda: recall_cal
    )
    out = await svc.disconnect("p1")
    assert out["recall_deregistered"] is True


@pytest.mark.asyncio
async def test_disconnect_recall_deregister_fails_raises(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    respx_mock.get(rest_url("user_connections")).mock(
        return_value=httpx.Response(200, json=[{"recall_calendar_id": "rc-1"}])
    )
    recall_cal = MagicMock()
    recall_cal.client = MagicMock()
    recall_cal.client.delete = AsyncMock(return_value=_resp(500))
    recall_cal.close = AsyncMock()
    monkeypatch.setattr(
        "app.services.recall_calendar_service.get_recall_calendar_service", lambda: recall_cal
    )
    with pytest.raises(RuntimeError, match="deregistration failed"):
        await svc.disconnect("p1")


# --------------------------------------------------------------------------
# find_available_slots
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_available_slots_computes_free_blocks(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "_get_valid_token", AsyncMock(return_value="tok"))
    # No busy periods → slots from work hours.
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(200, {"calendars": {"primary": {"busy": []}}}))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)

    # Far-future date so "now" filtering doesn't trim the day.
    out = await svc.find_available_slots("p1", "2030-06-01", "2030-06-01",
                                         duration_minutes=60, timezone_name="UTC",
                                         start_hour=9, end_hour=12)
    assert out["timezone"] == "UTC"
    assert len(out["slots"]) == 3  # 9-10, 10-11, 11-12


@pytest.mark.asyncio
async def test_find_available_slots_freebusy_error_raises(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "_get_valid_token", AsyncMock(return_value="tok"))
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(403, text="forbidden"))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    with pytest.raises(ValueError, match="availability"):
        await svc.find_available_slots("p1", "2030-06-01", "2030-06-01", timezone_name="UTC")


@pytest.mark.asyncio
async def test_find_available_slots_subtracts_busy(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "_get_valid_token", AsyncMock(return_value="tok"))
    busy = {"calendars": {"primary": {"busy": [
        {"start": "2030-06-01T10:00:00+00:00", "end": "2030-06-01T11:00:00+00:00"},
    ]}}}
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(200, busy))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    out = await svc.find_available_slots("p1", "2030-06-01", "2030-06-01",
                                         duration_minutes=60, timezone_name="UTC",
                                         start_hour=9, end_hour=12)
    starts = [s["start"] for s in out["slots"]]
    # 10:00 slot is busy; 9-10 and 11-12 remain.
    assert any("T09:00" in s for s in starts)
    assert not any("T10:00" in s for s in starts)


# --------------------------------------------------------------------------
# create_meet_event / create_calendar_event
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_meet_event_success(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "_get_valid_token", AsyncMock(return_value="tok"))
    data = {
        "id": "ev-1", "htmlLink": "http://cal",
        "conferenceData": {"entryPoints": [{"entryPointType": "video", "uri": "http://meet"}]},
    }
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(200, data))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    out = await svc.create_meet_event("p1", "Interview", "2030-06-01T10:00:00Z",
                                      "2030-06-01T11:00:00Z", attendees=["a@b.com"],
                                      timezone_override="UTC")
    assert out["event_id"] == "ev-1"
    assert out["meet_link"] == "http://meet"


@pytest.mark.asyncio
async def test_create_meet_event_no_meet_link_raises(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "_get_valid_token", AsyncMock(return_value="tok"))
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(200, {"id": "ev-1", "conferenceData": {"entryPoints": []}}))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    with pytest.raises(ValueError, match="no Meet link"):
        await svc.create_meet_event("p1", "T", "2030-06-01T10:00:00Z", "2030-06-01T11:00:00Z",
                                    timezone_override="UTC")


@pytest.mark.asyncio
async def test_create_meet_event_http_error_raises(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "_get_valid_token", AsyncMock(return_value="tok"))
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(400, text="bad"))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    with pytest.raises(ValueError, match="Failed to create"):
        await svc.create_meet_event("p1", "T", "2030-06-01T10:00:00Z", "2030-06-01T11:00:00Z",
                                    timezone_override="UTC")


@pytest.mark.asyncio
async def test_create_meet_event_fetches_profile_timezone(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "_get_valid_token", AsyncMock(return_value="tok"))
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[{"timezone": "America/New_York"}])
    )
    data = {"id": "ev-1", "htmlLink": "http://cal",
            "conferenceData": {"entryPoints": [{"entryPointType": "video", "uri": "http://meet"}]}}
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(201, data))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    out = await svc.create_meet_event("p1", "T", "2030-06-01T10:00:00Z", "2030-06-01T11:00:00Z")
    assert out["event_id"] == "ev-1"
    body = client.post.call_args.kwargs["json"]
    assert body["start"]["timeZone"] == "America/New_York"


@pytest.mark.asyncio
async def test_create_calendar_event_success(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "_get_valid_token", AsyncMock(return_value="tok"))
    respx_mock.get(rest_url("profiles")).mock(return_value=httpx.Response(200, json=[{"timezone": "UTC"}]))
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(200, {"id": "ev-2", "htmlLink": "http://cal2"}))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    out = await svc.create_calendar_event("p1", "Sync", "2030-06-01T10:00:00Z", "2030-06-01T11:00:00Z",
                                          location="Room 1")
    assert out["event_id"] == "ev-2"
    body = client.post.call_args.kwargs["json"]
    assert body["location"] == "Room 1"


@pytest.mark.asyncio
async def test_create_calendar_event_error_raises(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "_get_valid_token", AsyncMock(return_value="tok"))
    respx_mock.get(rest_url("profiles")).mock(return_value=httpx.Response(200, json=[{"timezone": "UTC"}]))
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(400, text="bad"))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    with pytest.raises(ValueError, match="Failed to create"):
        await svc.create_calendar_event("p1", "Sync", "2030-06-01T10:00:00Z", "2030-06-01T11:00:00Z")


# --------------------------------------------------------------------------
# backfill_recall_registrations + factory
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backfill_disabled_skips(monkeypatch):
    svc = _make_service(monkeypatch)
    settings = gcs.get_settings()
    monkeypatch.setattr(settings, "CALENDAR_INTELLIGENCE_ENABLED", False, raising=False)
    out = await svc.backfill_recall_registrations()
    assert out == {"skipped": True, "reason": "feature disabled"}


@pytest.mark.asyncio
async def test_backfill_tallies(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    settings = gcs.get_settings()
    monkeypatch.setattr(settings, "CALENDAR_INTELLIGENCE_ENABLED", True, raising=False)
    respx_mock.get(rest_url("user_connections")).mock(
        return_value=httpx.Response(200, json=[
            {"profile_id": "p1", "organization_id": "o1"},
            {"profile_id": "p2", "organization_id": "o1"},
            {"profile_id": "p3", "organization_id": "o1"},
        ])
    )

    async def fake_register(profile_id, org_id):
        if profile_id == "p1":
            return True
        if profile_id == "p2":
            return False
        raise RuntimeError("boom")

    monkeypatch.setattr(svc, "register_with_recall", AsyncMock(side_effect=fake_register))
    out = await svc.backfill_recall_registrations()
    assert out["total"] == 3
    assert out["registered"] == 1
    assert out["failed"] == 2
    assert set(out["failed_profiles"]) == {"p2", "p3"}


def test_factory():
    assert isinstance(get_google_calendar_service(), GoogleCalendarService)
