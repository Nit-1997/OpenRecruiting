"""Characterization tests for webhooks_slack helpers:
verify_slack_signature, _get_action_label, _get_effective_slack_features,
handle_app_home_opened, handle_block_action crash isolation.
"""

import hashlib
import hmac
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v2.routers import webhooks_slack as ws


# ----------------------- verify_slack_signature -----------------------

def _settings(secret="slack-signing-secret"):
    return SimpleNamespace(SLACK_SIGNING_SECRET=secret, ENV="test")


def _sign(secret, ts, body: bytes):
    base = f"v0:{ts}:{body.decode()}".encode()
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def test_verify_slack_signature_no_secret():
    with patch.object(ws, "get_settings", lambda: _settings(secret="")):
        assert ws.verify_slack_signature("123", b"{}", "v0=x") is False


def test_verify_slack_signature_missing_ts_or_sig():
    with patch.object(ws, "get_settings", _settings):
        assert ws.verify_slack_signature("", b"{}", "v0=x") is False
        assert ws.verify_slack_signature("123", b"{}", "") is False


def test_verify_slack_signature_bad_ts():
    with patch.object(ws, "get_settings", _settings):
        assert ws.verify_slack_signature("notanint", b"{}", "v0=x") is False


def test_verify_slack_signature_stale_ts():
    with patch.object(ws, "get_settings", _settings):
        assert ws.verify_slack_signature("1000", b"{}", "v0=x") is False


def test_verify_slack_signature_valid():
    ts = str(int(time.time()))
    body = b'{"event":"x"}'
    sig = _sign("slack-signing-secret", ts, body)
    with patch.object(ws, "get_settings", _settings):
        assert ws.verify_slack_signature(ts, body, sig) is True


def test_verify_slack_signature_mismatch():
    ts = str(int(time.time()))
    with patch.object(ws, "get_settings", _settings):
        assert ws.verify_slack_signature(ts, b"{}", "v0=deadbeef") is False


# ----------------------- _get_action_label -----------------------

def test_get_action_label_dict_text():
    assert ws._get_action_label({"text": {"text": "Click me"}}) == "Click me"


def test_get_action_label_string_text():
    assert ws._get_action_label({"text": "Plain"}) == "Plain"


def test_get_action_label_empty():
    assert ws._get_action_label({}) == ""


# ----------------------- _get_effective_slack_features -----------------------

@pytest.mark.asyncio
async def test_effective_features_no_org_returns_defaults():
    out = await ws._get_effective_slack_features(None, {})
    assert out == ws._DEFAULT_SLACK_FEATURES


@pytest.mark.asyncio
async def test_effective_features_org_override():
    sb = MagicMock()
    builder = MagicMock()
    builder.select.return_value = builder
    builder.eq.return_value = builder
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[{"slack_features": {"assistant_write": True}}]))
    sb.table.return_value = builder
    with patch("app.services.supabase.get_supabase_admin_client", return_value=sb):
        out = await ws._get_effective_slack_features("org1", {})
    assert out["assistant_write"] is True


@pytest.mark.asyncio
async def test_effective_features_user_overrides_org():
    sb = MagicMock()
    builder = MagicMock()
    builder.select.return_value = builder
    builder.eq.return_value = builder
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[{"slack_features": {"assistant_read": False}}]))
    sb.table.return_value = builder
    with patch("app.services.supabase.get_supabase_admin_client", return_value=sb):
        out = await ws._get_effective_slack_features("org1", {"user_slack_features": {"assistant_read": True}})
    assert out["assistant_read"] is True  # user wins


@pytest.mark.asyncio
async def test_effective_features_lookup_failure_test_env_fallback():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("db down")
    with patch("app.services.supabase.get_supabase_admin_client", return_value=sb), \
         patch.object(ws, "get_settings", _settings):
        out = await ws._get_effective_slack_features("org1", {})
    assert out["assistant_read"] is True  # test-env deterministic fallback


# ----------------------- handle_app_home_opened -----------------------

@pytest.mark.asyncio
async def test_home_opened_no_user_returns():
    await ws.handle_app_home_opened({}, "T1")  # no user_id


@pytest.mark.asyncio
async def test_home_opened_no_installation_returns():
    svc = MagicMock()
    svc.get_bot_token_for_team = AsyncMock(side_effect=ValueError("no install"))
    with patch.object(ws, "get_slack_service", return_value=svc):
        await ws.handle_app_home_opened({"user": "U1"}, "T1")


@pytest.mark.asyncio
async def test_home_opened_publishes_tab():
    svc = MagicMock()
    svc.get_bot_token_for_team = AsyncMock(return_value="tok")
    svc.get_connection = AsyncMock(return_value={"organization_id": "org1"})
    svc.publish_home_tab = AsyncMock()
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "limit"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[{"name": "Acme"}]))
    sb.table.return_value = builder
    with patch.object(ws, "get_slack_service", return_value=svc), \
         patch("app.services.supabase.get_supabase_admin_client", return_value=sb):
        await ws.handle_app_home_opened({"user": "U1"}, "T1")
    svc.publish_home_tab.assert_awaited_once()


# ----------------------- handle_block_action crash isolation -----------------------

@pytest.mark.asyncio
async def test_handle_block_action_swallows_inner_crash():
    with patch.object(ws, "_handle_block_action_inner", AsyncMock(side_effect=RuntimeError("boom"))):
        await ws.handle_block_action({"actions": [{}]})  # must not raise
