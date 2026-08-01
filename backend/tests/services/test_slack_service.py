"""Unit tests for SlackService (BE-T7 coverage).

Covers: OAuth state mint/verify, Fernet token encrypt/decrypt round-trip,
the generic _slack_api_call with auth-retry, the message senders, token
refresh + the refresh-lock contention path, and the proactive/health/
backfill batch helpers.

All HTTP is mocked via a stubbed get_async_http_client; Supabase is mocked
via respx at http://test-supabase.local/rest/v1/*. asyncio.sleep is patched
so the refresh-lock wait loop never really blocks.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

from app.services import slack_service as ss
from app.services.slack_service import (
    SlackReauthRequiredError,
    SlackService,
    SlackServiceError,
    get_slack_service,
)

FERNET_KEY = Fernet.generate_key().decode()


def _make_service(monkeypatch) -> SlackService:
    """Build a SlackService with a real Fernet key configured."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "SLACK_ENCRYPTION_KEY", FERNET_KEY, raising=False)
    monkeypatch.setattr(settings, "SLACK_CLIENT_ID", "cid", raising=False)
    monkeypatch.setattr(settings, "SLACK_CLIENT_SECRET", "csec", raising=False)
    monkeypatch.setattr(settings, "SLACK_REDIRECT_URI", "https://app/cb", raising=False)
    svc = SlackService()
    # Make refresh waits instant for the contention test.
    svc._refresh_wait_interval_seconds = 0.0
    return svc


def _resp(status: int = 200, json_body: dict | None = None):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.content = b"{}"
    r.json.return_value = json_body if json_body is not None else {}
    return r


# --------------------------------------------------------------------------
# Crypto + OAuth state
# --------------------------------------------------------------------------

def test_encrypt_decrypt_round_trip(monkeypatch):
    svc = _make_service(monkeypatch)
    enc = svc.encrypt_token("xoxb-secret")
    assert enc != "xoxb-secret"
    assert svc.decrypt_token(enc) == "xoxb-secret"


def test_encrypt_without_key_raises():
    # No SLACK_ENCRYPTION_KEY → _fernet None → RuntimeError.
    svc = SlackService()
    assert svc._fernet is None
    with pytest.raises(RuntimeError):
        svc.encrypt_token("x")
    with pytest.raises(RuntimeError):
        svc.decrypt_token("x")
    with pytest.raises(RuntimeError):
        svc.create_oauth_state("u", "o")
    with pytest.raises(RuntimeError):
        svc.verify_oauth_state("state")


def test_oauth_state_mint_and_verify_round_trip(monkeypatch):
    svc = _make_service(monkeypatch)
    state = svc.create_oauth_state("user-1", "org-1")
    data = svc.verify_oauth_state(state)
    assert data["user_id"] == "user-1"
    assert data["org_id"] == "org-1"
    assert data["exp"] > time.time()


def test_oauth_state_expired_raises(monkeypatch):
    svc = _make_service(monkeypatch)
    payload = json.dumps({"user_id": "u", "org_id": "o", "exp": int(time.time()) - 10})
    expired = svc._fernet.encrypt(payload.encode()).decode()
    with pytest.raises(ValueError, match="expired"):
        svc.verify_oauth_state(expired)


def test_oauth_state_tampered_raises(monkeypatch):
    svc = _make_service(monkeypatch)
    with pytest.raises(ValueError, match="Invalid OAuth state"):
        svc.verify_oauth_state("not-a-valid-fernet-token")


# --------------------------------------------------------------------------
# exchange_code / _exchange_refresh_token
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exchange_code_success(monkeypatch):
    svc = _make_service(monkeypatch)
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(200, {"ok": True, "access_token": "t"}))
    monkeypatch.setattr(ss, "get_async_http_client", lambda: client)

    data = await svc.exchange_code("the-code")
    assert data["access_token"] == "t"
    sent = client.post.call_args
    assert sent.kwargs["data"]["code"] == "the-code"
    assert sent.kwargs["data"]["client_id"] == "cid"


@pytest.mark.asyncio
async def test_exchange_code_failure_raises(monkeypatch):
    svc = _make_service(monkeypatch)
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(200, {"ok": False, "error": "bad_code"}))
    monkeypatch.setattr(ss, "get_async_http_client", lambda: client)

    with pytest.raises(ValueError, match="bad_code"):
        await svc.exchange_code("x")


@pytest.mark.asyncio
async def test_exchange_refresh_token_failure_raises_reauth(monkeypatch):
    svc = _make_service(monkeypatch)
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(200, {"ok": False, "error": "invalid_grant"}))
    monkeypatch.setattr(ss, "get_async_http_client", lambda: client)

    with pytest.raises(SlackReauthRequiredError, match="invalid_grant"):
        await svc._exchange_refresh_token("refresh-tok")


# --------------------------------------------------------------------------
# _should_refresh / _parse_expiry
# --------------------------------------------------------------------------

def test_should_refresh_force(monkeypatch):
    svc = _make_service(monkeypatch)
    assert svc._should_refresh({}, force_refresh=True) is True


def test_should_refresh_no_expiry_false(monkeypatch):
    svc = _make_service(monkeypatch)
    assert svc._should_refresh({}) is False
    assert svc._parse_expiry({}) is None
    assert svc._parse_expiry({"token_expires_at": "not-a-date"}) is None


def test_should_refresh_expiring_soon_true(monkeypatch):
    svc = _make_service(monkeypatch)
    soon = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    assert svc._should_refresh({"token_expires_at": soon}) is True


def test_should_refresh_far_future_false(monkeypatch):
    svc = _make_service(monkeypatch)
    far = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    assert svc._should_refresh({"token_expires_at": far}) is False


# --------------------------------------------------------------------------
# _is_auth_error + _slack_api_call (happy / non-auth error / auth-retry)
# --------------------------------------------------------------------------

def test_is_auth_error():
    assert SlackService._is_auth_error({"error": "invalid_auth"}) is True
    assert SlackService._is_auth_error({"error": "token_revoked"}) is True
    assert SlackService._is_auth_error({"error": "channel_not_found"}) is False
    assert SlackService._is_auth_error({}) is False


@pytest.mark.asyncio
async def test_slack_api_call_success(monkeypatch):
    svc = _make_service(monkeypatch)
    client = MagicMock()
    client.request = AsyncMock(return_value=_resp(200, {"ok": True, "ts": "1.2"}))
    monkeypatch.setattr(ss, "get_async_http_client", lambda: client)

    data = await svc._slack_api_call(
        method="POST", endpoint="chat.postMessage", bot_token="xoxb",
        json_payload={"channel": "C1", "text": "hi"},
    )
    assert data["ts"] == "1.2"
    call = client.request.call_args
    assert call.kwargs["headers"]["Authorization"] == "Bearer xoxb"
    assert call.kwargs["url"].endswith("/chat.postMessage")


@pytest.mark.asyncio
async def test_slack_api_call_non_auth_error_returned(monkeypatch):
    svc = _make_service(monkeypatch)
    client = MagicMock()
    client.request = AsyncMock(return_value=_resp(200, {"ok": False, "error": "channel_not_found"}))
    monkeypatch.setattr(ss, "get_async_http_client", lambda: client)

    data = await svc._slack_api_call(
        method="POST", endpoint="chat.postMessage", bot_token="xoxb", team_id="T1",
    )
    # Non-auth error is returned as-is, no retry.
    assert data["error"] == "channel_not_found"
    assert client.request.call_count == 1


@pytest.mark.asyncio
async def test_slack_api_call_auth_retry_succeeds(monkeypatch):
    svc = _make_service(monkeypatch)
    client = MagicMock()
    client.request = AsyncMock(side_effect=[
        _resp(200, {"ok": False, "error": "invalid_auth"}),
        _resp(200, {"ok": True, "ts": "9.9"}),
    ])
    monkeypatch.setattr(ss, "get_async_http_client", lambda: client)
    monkeypatch.setattr(svc, "get_bot_token_for_team", AsyncMock(return_value="xoxb-fresh"))

    data = await svc._slack_api_call(
        method="POST", endpoint="chat.postMessage", bot_token="xoxb-stale", team_id="T1",
    )
    assert data["ok"] is True
    assert client.request.call_count == 2
    # Retry used the freshly-refreshed token.
    assert client.request.call_args.kwargs["headers"]["Authorization"] == "Bearer xoxb-fresh"
    svc.get_bot_token_for_team.assert_awaited_once()


@pytest.mark.asyncio
async def test_slack_api_call_auth_retry_still_auth_error_marks_reauth(monkeypatch):
    svc = _make_service(monkeypatch)
    client = MagicMock()
    client.request = AsyncMock(side_effect=[
        _resp(200, {"ok": False, "error": "invalid_auth"}),
        _resp(200, {"ok": False, "error": "token_revoked"}),
    ])
    monkeypatch.setattr(ss, "get_async_http_client", lambda: client)
    monkeypatch.setattr(svc, "get_bot_token_for_team", AsyncMock(return_value="xoxb-fresh"))
    marked = AsyncMock()
    monkeypatch.setattr(svc, "_mark_needs_reauth_by_team", marked)

    with pytest.raises(SlackReauthRequiredError):
        await svc._slack_api_call(
            method="POST", endpoint="chat.postMessage", bot_token="x", team_id="T1",
        )
    marked.assert_awaited_once()


@pytest.mark.asyncio
async def test_slack_api_call_refresh_raises_reauth_marks_team(monkeypatch):
    svc = _make_service(monkeypatch)
    client = MagicMock()
    client.request = AsyncMock(return_value=_resp(200, {"ok": False, "error": "invalid_auth"}))
    monkeypatch.setattr(ss, "get_async_http_client", lambda: client)
    monkeypatch.setattr(
        svc, "get_bot_token_for_team",
        AsyncMock(side_effect=SlackReauthRequiredError("reconnect")),
    )
    marked = AsyncMock()
    monkeypatch.setattr(svc, "_mark_needs_reauth_by_team", marked)

    with pytest.raises(SlackReauthRequiredError):
        await svc._slack_api_call(
            method="POST", endpoint="chat.postMessage", bot_token="x", team_id="T1",
        )
    marked.assert_awaited_once()


# --------------------------------------------------------------------------
# Message senders
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_message_passes_blocks_and_thread(monkeypatch):
    svc = _make_service(monkeypatch)
    api = AsyncMock(return_value={"ok": True, "ts": "1.1"})
    monkeypatch.setattr(svc, "_slack_api_call", api)

    out = await svc.send_message("xoxb", "C1", "hello", blocks=[{"x": 1}], thread_ts="t0", team_id="T1")
    assert out["ts"] == "1.1"
    payload = api.call_args.kwargs["json_payload"]
    assert payload["channel"] == "C1"
    assert payload["blocks"] == [{"x": 1}]
    assert payload["thread_ts"] == "t0"


@pytest.mark.asyncio
async def test_send_message_logs_on_failure(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "_slack_api_call", AsyncMock(return_value={"ok": False, "error": "boom"}))
    out = await svc.send_message("xoxb", "C1", "hello")
    assert out["error"] == "boom"


@pytest.mark.asyncio
async def test_update_message(monkeypatch):
    svc = _make_service(monkeypatch)
    api = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(svc, "_slack_api_call", api)
    await svc.update_message("xoxb", "C1", "ts1", "new", blocks=[{"b": 1}], team_id="T1")
    payload = api.call_args.kwargs["json_payload"]
    assert payload["ts"] == "ts1"
    assert payload["blocks"] == [{"b": 1}]


@pytest.mark.asyncio
async def test_open_dm_channel_success_and_failure(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "_slack_api_call", AsyncMock(return_value={"ok": True, "channel": {"id": "D1"}}))
    assert await svc.open_dm_channel("xoxb", "U1") == "D1"

    monkeypatch.setattr(svc, "_slack_api_call", AsyncMock(return_value={"ok": False, "error": "cannot_dm_bot"}))
    with pytest.raises(ValueError, match="cannot_dm_bot"):
        await svc.open_dm_channel("xoxb", "U1")


@pytest.mark.asyncio
async def test_send_dm_opens_then_sends(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "open_dm_channel", AsyncMock(return_value="D9"))
    send = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(svc, "send_message", send)
    await svc.send_dm("xoxb", "U1", "hey", blocks=[{"b": 1}], team_id="T1")
    args = send.call_args.args
    assert args[1] == "D9"  # channel resolved from open_dm_channel


@pytest.mark.asyncio
async def test_publish_home_tab(monkeypatch):
    svc = _make_service(monkeypatch)
    api = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(svc, "_slack_api_call", api)
    await svc.publish_home_tab("xoxb", "U1", [{"b": 1}], team_id="T1")
    payload = api.call_args.kwargs["json_payload"]
    assert payload["user_id"] == "U1"
    assert payload["view"]["type"] == "home"


@pytest.mark.asyncio
async def test_get_user_info(monkeypatch):
    svc = _make_service(monkeypatch)
    api = AsyncMock(return_value={"ok": True, "user": {"id": "U1"}})
    monkeypatch.setattr(svc, "_slack_api_call", api)
    out = await svc.get_user_info("xoxb", "U1", team_id="T1")
    assert out["user"]["id"] == "U1"
    assert api.call_args.kwargs["params"] == {"user": "U1"}


@pytest.mark.asyncio
async def test_open_modal(monkeypatch):
    svc = _make_service(monkeypatch)
    api = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(svc, "_slack_api_call", api)
    await svc.open_modal("xoxb", "trig1", {"type": "modal"}, team_id="T1")
    payload = api.call_args.kwargs["json_payload"]
    assert payload["trigger_id"] == "trig1"


# --------------------------------------------------------------------------
# DB reads (respx-mocked Supabase)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_installation_by_team(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.get(rest_url("slack_installations")).mock(
        return_value=httpx.Response(200, json=[{"id": "i1", "slack_team_id": "T1"}])
    )
    out = await svc.get_installation_by_team("T1")
    assert out["id"] == "i1"


@pytest.mark.asyncio
async def test_get_installation_by_team_empty(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.get(rest_url("slack_installations")).mock(return_value=httpx.Response(200, json=[]))
    assert await svc.get_installation_by_team("T1") is None


@pytest.mark.asyncio
async def test_get_connection(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.get(rest_url("slack_connections")).mock(
        return_value=httpx.Response(200, json=[{"slack_user_id": "U1", "profile_id": "p1"}])
    )
    out = await svc.get_connection("U1", "T1")
    assert out["profile_id"] == "p1"


@pytest.mark.asyncio
async def test_find_slack_user_by_profile_email(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.get(rest_url("profiles")).mock(return_value=httpx.Response(200, json=[{"id": "p1"}]))
    respx_mock.get(rest_url("slack_connections")).mock(
        return_value=httpx.Response(200, json=[{"slack_user_id": "U-SLACK"}])
    )
    out = await svc.find_slack_user_by_profile_email("A@B.com", organization_id="o1", slack_team_id="T1")
    assert out == "U-SLACK"


@pytest.mark.asyncio
async def test_find_slack_user_empty_email_returns_none(monkeypatch):
    svc = _make_service(monkeypatch)
    assert await svc.find_slack_user_by_profile_email("") is None


@pytest.mark.asyncio
async def test_find_slack_user_no_profile_returns_none(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.get(rest_url("profiles")).mock(return_value=httpx.Response(200, json=[]))
    assert await svc.find_slack_user_by_profile_email("x@y.com") is None


# --------------------------------------------------------------------------
# get_bot_token_for_team gates
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_bot_token_no_installation_raises(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "get_installation_by_team", AsyncMock(return_value=None))
    with pytest.raises(ValueError, match="No active installation"):
        await svc.get_bot_token_for_team("T1")


@pytest.mark.asyncio
async def test_get_bot_token_needs_reauth_raises(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "get_installation_by_team",
                        AsyncMock(return_value={"id": "i1", "auth_state": "needs_reauth"}))
    with pytest.raises(SlackReauthRequiredError):
        await svc.get_bot_token_for_team("T1")


@pytest.mark.asyncio
async def test_get_bot_token_missing_encrypted_marks_reauth(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "get_installation_by_team",
                        AsyncMock(return_value={"id": "i1", "auth_state": "healthy"}))
    marked = AsyncMock()
    monkeypatch.setattr(svc, "_mark_needs_reauth_by_team", marked)
    with pytest.raises(SlackReauthRequiredError):
        await svc.get_bot_token_for_team("T1")
    marked.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_bot_token_no_refresh_decrypts(monkeypatch):
    svc = _make_service(monkeypatch)
    enc = svc.encrypt_token("xoxb-live")
    far = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    monkeypatch.setattr(
        svc, "get_installation_by_team",
        AsyncMock(return_value={"id": "i1", "auth_state": "healthy",
                                "bot_token_encrypted": enc, "token_expires_at": far}),
    )
    out = await svc.get_bot_token_for_team("T1")
    assert out == "xoxb-live"


@pytest.mark.asyncio
async def test_get_bot_token_triggers_refresh(monkeypatch):
    svc = _make_service(monkeypatch)
    enc = svc.encrypt_token("xoxb-refreshed")
    soon = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
    install = {"id": "i1", "auth_state": "healthy", "bot_token_encrypted": svc.encrypt_token("old"),
               "token_expires_at": soon}
    monkeypatch.setattr(svc, "get_installation_by_team", AsyncMock(return_value=install))
    refreshed_install = {"id": "i1", "bot_token_encrypted": enc}
    refresh = AsyncMock(return_value=refreshed_install)
    monkeypatch.setattr(svc, "_refresh_bot_token", refresh)

    out = await svc.get_bot_token_for_team("T1", force_refresh=True)
    assert out == "xoxb-refreshed"
    refresh.assert_awaited_once()


# --------------------------------------------------------------------------
# _refresh_bot_token (lock acquired, success + missing refresh token)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_bot_token_missing_refresh_marks_reauth(monkeypatch):
    svc = _make_service(monkeypatch)
    mark = AsyncMock()
    monkeypatch.setattr(svc, "_mark_needs_reauth", mark)
    with pytest.raises(SlackReauthRequiredError, match="missing refresh"):
        await svc._refresh_bot_token({"id": "i1"}, team_id="T1", reason="x")
    mark.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_bot_token_missing_id_raises(monkeypatch):
    svc = _make_service(monkeypatch)
    with pytest.raises(SlackServiceError, match="missing id"):
        await svc._refresh_bot_token({}, team_id="T1", reason="x")


@pytest.mark.asyncio
async def test_refresh_bot_token_success(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    install = {"id": "i1", "refresh_token_encrypted": svc.encrypt_token("refresh-old")}
    monkeypatch.setattr(svc, "_acquire_refresh_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(svc, "_release_refresh_lock", AsyncMock())
    monkeypatch.setattr(
        svc, "_exchange_refresh_token",
        AsyncMock(return_value={"access_token": "new-access", "refresh_token": "new-refresh",
                                "expires_in": 3600, "token_type": "bot"}),
    )
    final_install = {"id": "i1", "bot_token_encrypted": svc.encrypt_token("new-access")}
    monkeypatch.setattr(svc, "get_installation_by_team", AsyncMock(return_value=final_install))

    # The DB writes (auth_state=refreshing, then the token update) go to Supabase.
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.patch(rest_url("slack_installations")).mock(return_value=httpx.Response(200, json=[{"id": "i1"}]))

    out = await svc._refresh_bot_token(install, team_id="T1", reason="proactive", force_refresh=True)
    assert out == final_install
    svc._release_refresh_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_bot_token_missing_access_in_response_marks_reauth(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    install = {"id": "i1", "refresh_token_encrypted": svc.encrypt_token("refresh-old")}
    monkeypatch.setattr(svc, "_acquire_refresh_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(svc, "_release_refresh_lock", AsyncMock())
    monkeypatch.setattr(svc, "_exchange_refresh_token", AsyncMock(return_value={"expires_in": 3600}))
    mark = AsyncMock()
    monkeypatch.setattr(svc, "_mark_needs_reauth", mark)
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.patch(rest_url("slack_installations")).mock(return_value=httpx.Response(200, json=[{"id": "i1"}]))

    with pytest.raises(SlackReauthRequiredError):
        await svc._refresh_bot_token(install, team_id="T1", reason="x", force_refresh=True)
    mark.assert_awaited_once()
    svc._release_refresh_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_bot_token_lock_contention_resolved_by_peer(monkeypatch):
    """Lock not acquired → wait loop; peer finishes refresh so the freshly read
    installation no longer needs refresh → returns it without erroring."""
    svc = _make_service(monkeypatch)
    install = {"id": "i1", "refresh_token_encrypted": svc.encrypt_token("r")}
    monkeypatch.setattr(svc, "_acquire_refresh_lock", AsyncMock(return_value=False))
    far = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    fresh = {"id": "i1", "auth_state": "healthy", "token_expires_at": far}
    monkeypatch.setattr(svc, "get_installation_by_team", AsyncMock(return_value=fresh))

    with patch.object(ss.asyncio, "sleep", AsyncMock()):
        out = await svc._refresh_bot_token(install, team_id="T1", reason="x")
    assert out == fresh


@pytest.mark.asyncio
async def test_refresh_bot_token_lock_contention_peer_needs_reauth(monkeypatch):
    svc = _make_service(monkeypatch)
    install = {"id": "i1", "refresh_token_encrypted": svc.encrypt_token("r")}
    monkeypatch.setattr(svc, "_acquire_refresh_lock", AsyncMock(return_value=False))
    monkeypatch.setattr(
        svc, "get_installation_by_team",
        AsyncMock(return_value={"id": "i1", "auth_state": "needs_reauth"}),
    )
    with patch.object(ss.asyncio, "sleep", AsyncMock()):
        with pytest.raises(SlackReauthRequiredError):
            await svc._refresh_bot_token(install, team_id="T1", reason="x")


@pytest.mark.asyncio
async def test_refresh_bot_token_lock_contention_timeout(monkeypatch):
    svc = _make_service(monkeypatch)
    svc._refresh_wait_attempts = 2
    install = {"id": "i1", "refresh_token_encrypted": svc.encrypt_token("r")}
    monkeypatch.setattr(svc, "_acquire_refresh_lock", AsyncMock(return_value=False))
    soon = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    monkeypatch.setattr(
        svc, "get_installation_by_team",
        AsyncMock(return_value={"id": "i1", "auth_state": "healthy", "token_expires_at": soon}),
    )
    with patch.object(ss.asyncio, "sleep", AsyncMock()):
        with pytest.raises(SlackServiceError, match="contention"):
            await svc._refresh_bot_token(install, team_id="T1", reason="x", force_refresh=True)


# --------------------------------------------------------------------------
# _acquire_refresh_lock branches
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_refresh_lock_no_id_false(monkeypatch):
    svc = _make_service(monkeypatch)
    assert await svc._acquire_refresh_lock({}) is False


@pytest.mark.asyncio
async def test_acquire_refresh_lock_held_by_self(monkeypatch):
    svc = _make_service(monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    install = {"id": "i1", "refresh_lock_at": now, "refresh_lock_owner": svc._lock_owner}
    assert await svc._acquire_refresh_lock(install) is True


@pytest.mark.asyncio
async def test_acquire_refresh_lock_held_by_other_recent(monkeypatch):
    svc = _make_service(monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    install = {"id": "i1", "refresh_lock_at": now, "refresh_lock_owner": "someone-else"}
    assert await svc._acquire_refresh_lock(install) is False


@pytest.mark.asyncio
async def test_acquire_refresh_lock_stale_takeover(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    stale = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
    install = {"id": "i1", "refresh_lock_at": stale, "refresh_lock_owner": "old-owner"}
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.patch(rest_url("slack_installations")).mock(
        return_value=httpx.Response(200, json=[{"id": "i1"}])
    )
    assert await svc._acquire_refresh_lock(install) is True


@pytest.mark.asyncio
async def test_acquire_refresh_lock_unlocked_takeover(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    install = {"id": "i1"}  # no lock currently
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.patch(rest_url("slack_installations")).mock(
        return_value=httpx.Response(200, json=[{"id": "i1"}])
    )
    assert await svc._acquire_refresh_lock(install) is True


# --------------------------------------------------------------------------
# _mark_needs_reauth / _release_refresh_lock / _mark_needs_reauth_by_team
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_needs_reauth_writes(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    from tests.helpers.supabase_mocks import rest_url
    route = respx_mock.patch(rest_url("slack_installations")).mock(
        return_value=httpx.Response(200, json=[{"id": "i1"}])
    )
    await svc._mark_needs_reauth("i1", error_code="invalid_auth")
    assert route.called


@pytest.mark.asyncio
async def test_release_refresh_lock(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    from tests.helpers.supabase_mocks import rest_url
    route = respx_mock.patch(rest_url("slack_installations")).mock(
        return_value=httpx.Response(200, json=[{"id": "i1"}])
    )
    await svc._release_refresh_lock("i1")
    assert route.called


@pytest.mark.asyncio
async def test_mark_needs_reauth_by_team_no_install_noop(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "get_installation_by_team", AsyncMock(return_value=None))
    # Should silently return without raising.
    await svc._mark_needs_reauth_by_team("T1", "invalid_auth")


@pytest.mark.asyncio
async def test_mark_needs_reauth_by_team_calls_mark(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "get_installation_by_team", AsyncMock(return_value={"id": "i1"}))
    mark = AsyncMock()
    monkeypatch.setattr(svc, "_mark_needs_reauth", mark)
    await svc._mark_needs_reauth_by_team("T1", "invalid_auth")
    mark.assert_awaited_once_with("i1", error_code="invalid_auth")


# --------------------------------------------------------------------------
# Batch helpers
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_expiring_installations_tally(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.get(rest_url("slack_installations")).mock(
        return_value=httpx.Response(200, json=[
            {"slack_team_id": "T1"}, {"slack_team_id": "T2"}, {"slack_team_id": "T3"}, {"slack_team_id": None},
        ])
    )

    async def fake_get_token(team_id, **kw):
        if team_id == "T1":
            return "tok"
        if team_id == "T2":
            raise SlackReauthRequiredError("x")
        raise RuntimeError("boom")

    monkeypatch.setattr(svc, "get_bot_token_for_team", AsyncMock(side_effect=fake_get_token))
    out = await svc.refresh_expiring_installations()
    assert out == {"checked": 4, "refreshed": 1, "reauth_required": 1, "failed": 1}


@pytest.mark.asyncio
async def test_get_installation_health_summary(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    now = datetime.now(timezone.utc)
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.get(rest_url("slack_installations")).mock(
        return_value=httpx.Response(200, json=[
            {"auth_state": "healthy", "token_expires_at": (now + timedelta(minutes=5)).isoformat()},
            {"auth_state": "healthy", "token_expires_at": (now + timedelta(minutes=40)).isoformat()},
            {"auth_state": "needs_reauth", "token_expires_at": (now + timedelta(hours=3)).isoformat()},
            {"auth_state": "bogus_state", "token_expires_at": None},
        ])
    )
    out = await svc.get_installation_health_summary()
    assert out["total_active_installations"] == 4
    assert out["auth_state_counts"]["healthy"] == 2
    assert out["auth_state_counts"]["needs_reauth"] == 1
    assert out["auth_state_counts"]["unknown"] == 1
    assert out["expiry_buckets"]["lt_15m"] == 1
    assert out["expiry_buckets"]["lt_1h"] == 1
    assert out["expiry_buckets"]["gte_1h"] == 1
    assert out["expiry_buckets"]["missing"] == 1


@pytest.mark.asyncio
async def test_force_refresh_team_token(monkeypatch):
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(svc, "get_bot_token_for_team", AsyncMock(return_value="tok"))
    monkeypatch.setattr(
        svc, "get_installation_by_team",
        AsyncMock(return_value={"auth_state": "healthy", "token_expires_at": "2030-01-01T00:00:00+00:00"}),
    )
    out = await svc.force_refresh_team_token("T1")
    assert out["team_id"] == "T1"
    assert out["auth_state"] == "healthy"
    assert out["refreshed"] is True


@pytest.mark.asyncio
async def test_backfill_auth_state(monkeypatch, respx_mock):
    svc = _make_service(monkeypatch)
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.get(rest_url("slack_installations")).mock(
        return_value=httpx.Response(200, json=[
            {"id": "i1", "auth_state": "healthy", "refresh_token_encrypted": "r", "token_expires_at": "t"},  # has rotation → skip
            {"id": "i2", "auth_state": "needs_reauth"},  # already reauth → skip
            {"id": "i3", "auth_state": "healthy"},  # missing rotation → update
            {"auth_state": "healthy"},  # no id → skip
        ])
    )
    mark = AsyncMock()
    monkeypatch.setattr(svc, "_mark_needs_reauth", mark)
    out = await svc.backfill_auth_state()
    assert out["checked"] == 4
    assert out["updated_to_needs_reauth"] == 1
    assert out["skipped"] == 3
    mark.assert_awaited_once()


def test_get_slack_service_factory():
    assert isinstance(get_slack_service(), SlackService)
