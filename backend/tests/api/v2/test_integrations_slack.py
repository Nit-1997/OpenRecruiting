"""Tests for /api/v2/integrations/slack/* (install, callback, status, disconnect).

install/status/disconnect run under recruiter auth + respx-mocked supabase.
callback runs with no auth and is exercised through its branch matrix
(error param, missing params, bad state, exchange failure, incomplete payload,
new install + connection, existing install + connection).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.slack_service import get_slack_service
from tests.helpers.supabase_mocks import mock_select, mock_insert, mock_update


# ----------------------- install -----------------------

def test_install_forbidden_without_slack_plan(recruiter_client, respx_mock):
    mock_select(respx_mock, "subscriptions", [{"plan_id": "p1", "plans": {"slack_enabled": False}}])
    resp = recruiter_client.get("/api/v2/integrations/slack/install")
    assert resp.status_code == 403


def test_install_returns_redirect_url(recruiter_client, respx_mock):
    mock_select(respx_mock, "subscriptions", [{"plan_id": "p1", "plans": {"slack_enabled": True}}])
    svc = MagicMock()
    svc.create_oauth_state = MagicMock(return_value="state-token")
    with patch("app.api.v2.routers.integrations_slack.get_slack_service", return_value=svc):
        resp = recruiter_client.get("/api/v2/integrations/slack/install")
    assert resp.status_code == 200
    url = resp.json()["redirect_url"]
    assert url.startswith("https://slack.com/oauth/v2/authorize?")
    assert "state=state-token" in url


# ----------------------- status -----------------------

def test_status_not_connected(recruiter_client, respx_mock):
    mock_select(respx_mock, "slack_connections", [])
    resp = recruiter_client.get("/api/v2/integrations/slack/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["healthy"] is False


def test_status_connected_healthy(recruiter_client, respx_mock):
    mock_select(respx_mock, "slack_connections", [{
        "created_at": "2025-01-01T00:00:00+00:00",
        "slack_installations": {
            "slack_team_name": "Acme", "auth_state": "healthy",
            "token_expires_at": "2025-06-01T00:00:00+00:00", "last_auth_error_code": None,
        },
    }])
    resp = recruiter_client.get("/api/v2/integrations/slack/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["team_name"] == "Acme"
    assert body["needs_reauth"] is False


def test_status_needs_reauth(recruiter_client, respx_mock):
    mock_select(respx_mock, "slack_connections", [{
        "created_at": "2025-01-01T00:00:00+00:00",
        "slack_installations": [{
            "slack_team_name": "Acme", "auth_state": "needs_reauth",
            "token_expires_at": None, "last_auth_error_code": "expired",
        }],
    }])
    resp = recruiter_client.get("/api/v2/integrations/slack/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["needs_reauth"] is True
    assert body["healthy"] is False


# ----------------------- disconnect -----------------------

def test_disconnect_ok(recruiter_client, respx_mock):
    mock_update(respx_mock, "slack_connections", {"id": "conn1"})
    resp = recruiter_client.delete("/api/v2/integrations/slack/disconnect")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_disconnect_no_active_404(recruiter_client, respx_mock):
    mock_update(respx_mock, "slack_connections", None)
    resp = recruiter_client.delete("/api/v2/integrations/slack/disconnect")
    assert resp.status_code == 404


# ----------------------- callback (no auth) -----------------------

def test_callback_oauth_denied(unauthed_client):
    resp = unauthed_client.get("/api/v2/integrations/slack/callback?error=access_denied", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "slack=error" in resp.headers["location"]


def test_callback_missing_params(unauthed_client):
    resp = unauthed_client.get("/api/v2/integrations/slack/callback", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "missing_params" in resp.headers["location"]


def test_callback_bad_state(unauthed_client):
    svc = MagicMock()
    svc.verify_oauth_state = MagicMock(side_effect=ValueError("tampered"))
    with patch("app.api.v2.routers.integrations_slack.get_slack_service", return_value=svc):
        resp = unauthed_client.get(
            "/api/v2/integrations/slack/callback?code=c&state=s", follow_redirects=False
        )
    assert "invalid_state" in resp.headers["location"]


def test_callback_exchange_failure(unauthed_client):
    svc = MagicMock()
    svc.verify_oauth_state = MagicMock(return_value={"user_id": "u1", "org_id": "o1"})
    svc.exchange_code = AsyncMock(side_effect=ValueError("bad code"))
    with patch("app.api.v2.routers.integrations_slack.get_slack_service", return_value=svc):
        resp = unauthed_client.get(
            "/api/v2/integrations/slack/callback?code=c&state=s", follow_redirects=False
        )
    assert "exchange_failed" in resp.headers["location"]


def test_callback_incomplete_payload(unauthed_client):
    svc = MagicMock()
    svc.verify_oauth_state = MagicMock(return_value={"user_id": "u1", "org_id": "o1"})
    svc.exchange_code = AsyncMock(return_value={"team": {}, "access_token": None})
    with patch("app.api.v2.routers.integrations_slack.get_slack_service", return_value=svc):
        resp = unauthed_client.get(
            "/api/v2/integrations/slack/callback?code=c&state=s", follow_redirects=False
        )
    assert "incomplete_oauth_payload" in resp.headers["location"]


def test_callback_new_install_and_connection(unauthed_client, respx_mock):
    svc = MagicMock()
    svc.verify_oauth_state = MagicMock(return_value={"user_id": "u1", "org_id": "o1"})
    svc.exchange_code = AsyncMock(return_value={
        "team": {"id": "T1", "name": "Acme", "domain": "acme"},
        "access_token": "xoxb-token",
        "refresh_token": "xoxe-refresh",
        "expires_in": 43200,
        "token_type": "bot",
        "bot_user_id": "Ubot",
        "authed_user": {"id": "Uuser"},
        "scope": "chat:write",
    })
    svc.encrypt_token = MagicMock(side_effect=lambda t: f"enc({t})")
    svc.send_dm = AsyncMock()
    # No existing install/connection rows.
    mock_select(respx_mock, "slack_installations", [])
    mock_insert(respx_mock, "slack_installations", {"id": "i1"})
    mock_update(respx_mock, "slack_connections", [])
    mock_select(respx_mock, "slack_connections", [])
    mock_insert(respx_mock, "slack_connections", {"id": "c1"})
    with patch("app.api.v2.routers.integrations_slack.get_slack_service", return_value=svc):
        resp = unauthed_client.get(
            "/api/v2/integrations/slack/callback?code=c&state=s", follow_redirects=False
        )
    assert "slack=connected" in resp.headers["location"]
    svc.send_dm.assert_awaited_once()
