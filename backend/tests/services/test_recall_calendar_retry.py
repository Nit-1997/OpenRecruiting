"""BE-S2 resilience tests for RecallCalendarService.poll_events.

Covers:
  - retry on 429 (rate limit) then success
  - retry on 5xx then success
  - give up after max retries (returns partial, complete=False)
  - NO retry on a 4xx other than 429 (e.g. 403) — fail fast
  - ONE httpx.AsyncClient reused across paginated pages (no per-page client)
  - asyncio.sleep honors Retry-After + backs off (mocked, never really waits)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import recall_calendar_service as rcs
from app.services.recall_calendar_service import RecallCalendarService


def _resp(status: int, json_body: dict | None = None, headers: dict | None = None):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else {}
    r.text = ""
    r.headers = headers or {}
    return r


@pytest.fixture
def svc(monkeypatch):
    s = RecallCalendarService()
    # Make sleep deterministic / instant.
    return s


@pytest.mark.asyncio
async def test_poll_events_retries_on_429_then_succeeds(monkeypatch):
    s = RecallCalendarService()
    page = {"results": [{"id": "e1"}], "next": None}
    seq = [_resp(429, headers={"Retry-After": "2"}), _resp(200, page)]

    client = MagicMock()
    client.get = AsyncMock(side_effect=seq)
    monkeypatch.setattr(type(s), "client", property(lambda self: client))

    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    with patch.object(rcs.asyncio, "sleep", fake_sleep):
        events, complete = await s.poll_events(datetime.now(timezone.utc))

    assert complete is True
    assert events == [{"id": "e1"}]
    assert client.get.call_count == 2
    # Retry-After of 2s must be honored on the single backoff.
    assert sleeps and sleeps[0] >= 2.0


@pytest.mark.asyncio
async def test_poll_events_retries_on_5xx_then_succeeds(monkeypatch):
    s = RecallCalendarService()
    page = {"results": [{"id": "e1"}], "next": None}
    seq = [_resp(503), _resp(200, page)]

    client = MagicMock()
    client.get = AsyncMock(side_effect=seq)
    monkeypatch.setattr(type(s), "client", property(lambda self: client))

    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    with patch.object(rcs.asyncio, "sleep", fake_sleep):
        events, complete = await s.poll_events(datetime.now(timezone.utc))

    assert complete is True
    assert events == [{"id": "e1"}]
    assert client.get.call_count == 2
    assert len(sleeps) == 1


@pytest.mark.asyncio
async def test_poll_events_gives_up_after_max_retries(monkeypatch):
    s = RecallCalendarService()
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(429))
    monkeypatch.setattr(type(s), "client", property(lambda self: client))

    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    with patch.object(rcs.asyncio, "sleep", fake_sleep):
        events, complete = await s.poll_events(datetime.now(timezone.utc))

    # Exhausted retries → partial result, do NOT advance checkpoint.
    assert complete is False
    assert events == []
    # 1 initial + RETRY_MAX_ATTEMPTS-1 retries == RETRY_MAX_ATTEMPTS calls.
    assert client.get.call_count == rcs.RETRY_MAX_ATTEMPTS
    assert len(sleeps) == rcs.RETRY_MAX_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_poll_events_no_retry_on_403(monkeypatch):
    s = RecallCalendarService()
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(403))
    monkeypatch.setattr(type(s), "client", property(lambda self: client))

    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    with patch.object(rcs.asyncio, "sleep", fake_sleep):
        events, complete = await s.poll_events(datetime.now(timezone.utc))

    assert complete is False
    assert events == []
    # 403 is a hard client error — fail fast, no retry, no sleep.
    assert client.get.call_count == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_poll_events_reuses_single_client_across_pages(monkeypatch):
    """Following `next` must NOT construct a fresh httpx.AsyncClient per page."""
    s = RecallCalendarService()
    page1 = {"results": [{"id": "e1"}], "next": "https://api.recall.ai/api/v2/calendar-events/?cursor=abc"}
    page2 = {"results": [{"id": "e2"}], "next": None}

    client = MagicMock()
    client.get = AsyncMock(side_effect=[_resp(200, page1), _resp(200, page2)])
    monkeypatch.setattr(type(s), "client", property(lambda self: client))

    # If the impl creates a new AsyncClient for the http-prefixed next page,
    # this counter would be >0 and the test fails.
    construct_count = {"n": 0}
    real_init = httpx.AsyncClient.__init__

    def counting_init(self, *a, **kw):
        construct_count["n"] += 1
        return real_init(self, *a, **kw)

    with patch.object(httpx.AsyncClient, "__init__", counting_init):
        events, complete = await s.poll_events(datetime.now(timezone.utc))

    assert complete is True
    assert events == [{"id": "e1"}, {"id": "e2"}]
    assert client.get.call_count == 2
    assert construct_count["n"] == 0, "poll_events must reuse one client, not create per-page clients"
