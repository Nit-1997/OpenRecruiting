"""Unit tests for RecallCalendarService (BE-T7 coverage).

Complements test_recall_calendar_retry.py (poll_events backoff + single-client
pagination). Here we cover register_calendar, deploy_calendar_bot (incl. the
disallowed-bot_config-field retry), remove_calendar_bot, get_calendar_status,
poll page-cap, the disallowed-field helpers, the v1→v2 base_url rewrite, and
the standalone backoff helpers.

self.client is replaced with a MagicMock; Supabase is respx-mocked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import recall_calendar_service as rcs
from app.services.recall_calendar_service import (
    RecallCalendarService,
    _backoff_delay,
    _extract_disallowed_bot_config_fields,
    _is_retryable_status,
    _retry_after_seconds,
    _without_disallowed_bot_config_fields,
    get_recall_calendar_service,
)
from tests.helpers.supabase_mocks import rest_url


def _resp(status: int, json_body=None, text: str = "", headers=None):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else {}
    r.text = text
    r.headers = headers or {}
    return r


def _svc_with_client(monkeypatch, client) -> RecallCalendarService:
    s = RecallCalendarService()
    monkeypatch.setattr(type(s), "client", property(lambda self: client))
    return s


# --------------------------------------------------------------------------
# Module-level helpers
# --------------------------------------------------------------------------

def test_is_retryable_status():
    assert _is_retryable_status(429) is True
    assert _is_retryable_status(502) is True
    assert _is_retryable_status(404) is False


def test_retry_after_seconds():
    assert _retry_after_seconds(_resp(429, headers={"Retry-After": "7"})) == 7.0
    assert _retry_after_seconds(_resp(429, headers={"Retry-After": "x"})) is None
    assert _retry_after_seconds(None) is None


def test_backoff_delay():
    assert _backoff_delay(0, _resp(429, headers={"Retry-After": "99"})) == rcs.RETRY_MAX_BACKOFF_SECONDS
    d = _backoff_delay(0, _resp(500, headers={}))
    assert rcs.RETRY_BASE_SECONDS <= d <= rcs.RETRY_BASE_SECONDS + rcs.RETRY_JITTER_SECONDS


def test_extract_disallowed_fields_from_errors_dict():
    body = '{"errors": {"bot_config.recording_mode": ["This field is not allowed."]}}'
    out = _extract_disallowed_bot_config_fields(body)
    assert "recording_mode" in out


def test_extract_disallowed_fields_string_message():
    body = '{"errors": {"bot_config.foo": "foo is not allowed"}}'
    assert "foo" in _extract_disallowed_bot_config_fields(body)


def test_extract_disallowed_fields_fallback_non_json():
    # Truncated/non-JSON body still detects recording_mode via substring fallback.
    body = "... recording_mode is not allowed ..."
    assert "recording_mode" in _extract_disallowed_bot_config_fields(body)


def test_extract_disallowed_fields_empty():
    assert _extract_disallowed_bot_config_fields("") == set()
    assert _extract_disallowed_bot_config_fields("{}") == set()


def test_without_disallowed_fields_removes_only_present():
    payload = {"bot_config": {"recording_mode": "x", "keep": 1}}
    out = _without_disallowed_bot_config_fields(payload, {"recording_mode"})
    assert out["bot_config"] == {"keep": 1}
    # Nothing to remove → None.
    assert _without_disallowed_bot_config_fields(payload, {"absent"}) is None
    assert _without_disallowed_bot_config_fields(payload, set()) is None
    assert _without_disallowed_bot_config_fields({"no_bot_config": 1}, {"recording_mode"}) is None
    assert _without_disallowed_bot_config_fields("not-a-dict", {"x"}) is None


# --------------------------------------------------------------------------
# __init__ base_url rewrite + close + factory
# --------------------------------------------------------------------------

def test_base_url_rewrites_v1_to_v2(monkeypatch):
    settings = rcs.get_settings()
    monkeypatch.setattr(settings, "RECALL_BASE_URL", "https://us-west-2.recall.ai/api/v1", raising=False)
    s = RecallCalendarService()
    assert s.base_url == "https://us-west-2.recall.ai/api/v2"


@pytest.mark.asyncio
async def test_close_and_factory():
    s = RecallCalendarService()
    fake = MagicMock()
    fake.aclose = AsyncMock()
    s._client = fake
    await s.close()
    fake.aclose.assert_awaited_once()
    assert s._client is None
    assert isinstance(get_recall_calendar_service(), RecallCalendarService)


def test_client_lazy_construction():
    s = RecallCalendarService()
    assert s._client is None
    c = s.client
    assert c is s.client  # cached


# --------------------------------------------------------------------------
# register_calendar
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_calendar_success(monkeypatch, respx_mock):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(201, {"id": "rc-1"}))
    s = _svc_with_client(monkeypatch, client)
    respx_mock.patch(rest_url("user_connections")).mock(return_value=httpx.Response(200, json=[{"id": "c1"}]))
    out = await s.register_calendar("p1", "o1", "refresh", "a@b.com")
    assert out == "rc-1"


@pytest.mark.asyncio
async def test_register_calendar_rate_limited_none(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(429))
    s = _svc_with_client(monkeypatch, client)
    assert await s.register_calendar("p1", "o1", "r", "a@b.com") is None


@pytest.mark.asyncio
async def test_register_calendar_4xx_none(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(400, text="bad"))
    s = _svc_with_client(monkeypatch, client)
    assert await s.register_calendar("p1", "o1", "r", "a@b.com") is None


@pytest.mark.asyncio
async def test_register_calendar_no_id_none(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(201, {}))
    s = _svc_with_client(monkeypatch, client)
    assert await s.register_calendar("p1", "o1", "r", "a@b.com") is None


@pytest.mark.asyncio
async def test_register_calendar_exception_none(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
    s = _svc_with_client(monkeypatch, client)
    assert await s.register_calendar("p1", "o1", "r", "a@b.com") is None


# --------------------------------------------------------------------------
# deploy_calendar_bot
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deploy_calendar_bot_success(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(200, {"bot_id": "b1"}))
    s = _svc_with_client(monkeypatch, client)
    out = await s.deploy_calendar_bot("ev-1", {"bot_config": {"x": 1}})
    assert out == {"bot_id": "b1"}


@pytest.mark.asyncio
async def test_deploy_calendar_bot_retries_without_disallowed_fields(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(side_effect=[
        _resp(400, text='{"errors": {"bot_config.recording_mode": ["This field is not allowed."]}}'),
        _resp(200, {"bot_id": "b2"}),
    ])
    s = _svc_with_client(monkeypatch, client)
    out = await s.deploy_calendar_bot("ev-1", {"bot_config": {"recording_mode": "x", "keep": 1}})
    assert out == {"bot_id": "b2"}
    assert client.post.call_count == 2
    # Retry payload must have recording_mode stripped.
    retry_body = client.post.call_args_list[1].kwargs["json"]
    assert "recording_mode" not in retry_body["bot_config"]
    assert retry_body["bot_config"]["keep"] == 1


@pytest.mark.asyncio
async def test_deploy_calendar_bot_400_no_recoverable_fields_none(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(400, text="unrelated error"))
    s = _svc_with_client(monkeypatch, client)
    assert await s.deploy_calendar_bot("ev-1", {"bot_config": {"x": 1}}) is None
    assert client.post.call_count == 1


@pytest.mark.asyncio
async def test_deploy_calendar_bot_rate_limited_none(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(429))
    s = _svc_with_client(monkeypatch, client)
    assert await s.deploy_calendar_bot("ev-1", {}) is None


@pytest.mark.asyncio
async def test_deploy_calendar_bot_5xx_none(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(500, text="boom"))
    s = _svc_with_client(monkeypatch, client)
    assert await s.deploy_calendar_bot("ev-1", {}) is None


@pytest.mark.asyncio
async def test_deploy_calendar_bot_exception_none(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(side_effect=RuntimeError("net"))
    s = _svc_with_client(monkeypatch, client)
    assert await s.deploy_calendar_bot("ev-1", {}) is None


# --------------------------------------------------------------------------
# remove_calendar_bot
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_calendar_bot_success(monkeypatch):
    client = MagicMock()
    client.delete = AsyncMock(return_value=_resp(204))
    s = _svc_with_client(monkeypatch, client)
    assert await s.remove_calendar_bot("ev-1") is True


@pytest.mark.asyncio
async def test_remove_calendar_bot_error_false(monkeypatch):
    client = MagicMock()
    client.delete = AsyncMock(return_value=_resp(404, text="missing"))
    s = _svc_with_client(monkeypatch, client)
    assert await s.remove_calendar_bot("ev-1") is False


@pytest.mark.asyncio
async def test_remove_calendar_bot_exception_false(monkeypatch):
    client = MagicMock()
    client.delete = AsyncMock(side_effect=httpx.ConnectError("down"))
    s = _svc_with_client(monkeypatch, client)
    assert await s.remove_calendar_bot("ev-1") is False


# --------------------------------------------------------------------------
# get_calendar_status
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_calendar_status_success(monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(200, {"status": "connected"}))
    s = _svc_with_client(monkeypatch, client)
    assert (await s.get_calendar_status("rc-1"))["status"] == "connected"


@pytest.mark.asyncio
async def test_get_calendar_status_error_none(monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(404))
    s = _svc_with_client(monkeypatch, client)
    assert await s.get_calendar_status("rc-1") is None


@pytest.mark.asyncio
async def test_get_calendar_status_exception_none(monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(side_effect=RuntimeError("net"))
    s = _svc_with_client(monkeypatch, client)
    assert await s.get_calendar_status("rc-1") is None


# --------------------------------------------------------------------------
# poll_events — page cap (complementary to retry test file)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_events_hits_page_cap_returns_partial(monkeypatch):
    s = RecallCalendarService()
    # Every page has results AND a next URL → never terminates within max_pages.
    page = {"results": [{"id": "e"}], "next": "https://api.recall.ai/api/v2/calendar-events/?cursor=x"}
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(200, page))
    monkeypatch.setattr(type(s), "client", property(lambda self: client))

    with patch.object(rcs.asyncio, "sleep", AsyncMock()):
        events, complete = await s.poll_events(datetime.now(timezone.utc))

    # Hit the 50-page cap with more remaining → partial (complete=False).
    assert complete is False
    assert client.get.call_count == 50


@pytest.mark.asyncio
async def test_poll_events_empty_results_terminates(monkeypatch):
    s = RecallCalendarService()
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(200, {"results": [], "next": None}))
    monkeypatch.setattr(type(s), "client", property(lambda self: client))
    events, complete = await s.poll_events(datetime.now(timezone.utc))
    assert complete is True
    assert events == []
    assert client.get.call_count == 1
