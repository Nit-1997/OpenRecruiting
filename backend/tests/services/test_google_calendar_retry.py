"""BE-S2 resilience tests for GoogleCalendarService HTTP calls.

Google calls previously raised a hard ValueError on any transient 429/5xx.
Now they retry with bounded exponential backoff + jitter, honoring Retry-After,
on 429 + 5xx only — never on 4xx auth errors (401/403).

asyncio.sleep is mocked so tests never actually wait.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import google_calendar_service as gcs
from app.services.google_calendar_service import GoogleCalendarService


def _resp(status: int, json_body: dict | None = None, headers: dict | None = None):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else {}
    r.text = ""
    r.headers = headers or {}
    return r


@pytest.fixture
def svc():
    return GoogleCalendarService()


@pytest.mark.asyncio
async def test_userinfo_retries_on_429_then_succeeds(svc, monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(side_effect=[
        _resp(429, headers={"Retry-After": "3"}),
        _resp(200, {"email": "a@b.com"}),
    ])
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)

    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    with patch.object(gcs.asyncio, "sleep", fake_sleep):
        info = await svc.get_userinfo("tok")

    assert info == {"email": "a@b.com"}
    assert client.get.call_count == 2
    assert sleeps and sleeps[0] >= 3.0  # Retry-After honored


@pytest.mark.asyncio
async def test_userinfo_gives_up_after_max_retries(svc, monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(503))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)

    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    with patch.object(gcs.asyncio, "sleep", fake_sleep):
        with pytest.raises(ValueError):
            await svc.get_userinfo("tok")

    assert client.get.call_count == gcs.RETRY_MAX_ATTEMPTS
    assert len(sleeps) == gcs.RETRY_MAX_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_userinfo_no_retry_on_401(svc, monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(401))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)

    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    with patch.object(gcs.asyncio, "sleep", fake_sleep):
        with pytest.raises(ValueError):
            await svc.get_userinfo("tok")

    # Auth error → fail fast, no retry.
    assert client.get.call_count == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_refresh_token_retries_on_5xx_then_succeeds(svc, monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(side_effect=[
        _resp(500),
        _resp(200, {"access_token": "new", "expires_in": 3600}),
    ])
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    monkeypatch.setattr(svc, "decrypt_token", lambda enc: "refresh-tok")

    class _S:
        GOOGLE_CLIENT_ID = "cid"
        GOOGLE_CLIENT_SECRET = "csec"

    monkeypatch.setattr(gcs, "get_settings", lambda: _S())

    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    with patch.object(gcs.asyncio, "sleep", fake_sleep):
        data = await svc._refresh_token("enc-refresh")

    assert data["access_token"] == "new"
    assert client.post.call_count == 2
    assert len(sleeps) == 1


@pytest.mark.asyncio
async def test_refresh_token_no_retry_on_400(svc, monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(400, {"error": "invalid_grant"}))
    monkeypatch.setattr(gcs, "get_async_http_client", lambda: client)
    monkeypatch.setattr(svc, "decrypt_token", lambda enc: "refresh-tok")

    class _S:
        GOOGLE_CLIENT_ID = "cid"
        GOOGLE_CLIENT_SECRET = "csec"

    monkeypatch.setattr(gcs, "get_settings", lambda: _S())

    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    with patch.object(gcs.asyncio, "sleep", fake_sleep):
        with pytest.raises(ValueError):
            await svc._refresh_token("enc-refresh")

    assert client.post.call_count == 1
    assert sleeps == []
