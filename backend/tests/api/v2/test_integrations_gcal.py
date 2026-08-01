"""Tests for /api/v2/integrations/google-calendar/* routes.

install/status/disconnect delegate to GoogleCalendarService (mocked); the
calendar-watch + auto-join toggles use the get_supabase dependency (overridden);
callback runs unauth'd through its branch matrix.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v2.core.dependencies import get_supabase
from app.main import app


# ----------------------- install -----------------------

def test_install_returns_redirect(recruiter_client):
    svc = MagicMock()
    svc.create_oauth_state = MagicMock(return_value="state1")
    svc.build_oauth_url = MagicMock(return_value="https://accounts.google.com/o/oauth2?state=state1")
    with patch("app.api.v2.routers.integrations_gcal.get_google_calendar_service", return_value=svc):
        resp = recruiter_client.get("/api/v2/integrations/google-calendar/install")
    assert resp.status_code == 200
    assert resp.json()["redirect_url"].startswith("https://accounts.google.com")


def test_install_runtime_error_503(recruiter_client):
    svc = MagicMock()
    svc.create_oauth_state = MagicMock(side_effect=RuntimeError("oauth not configured"))
    with patch("app.api.v2.routers.integrations_gcal.get_google_calendar_service", return_value=svc):
        resp = recruiter_client.get("/api/v2/integrations/google-calendar/install")
    assert resp.status_code == 503


# ----------------------- status -----------------------

def test_status_not_connected(recruiter_client):
    svc = MagicMock()
    svc.get_connection = AsyncMock(return_value=None)
    with patch("app.api.v2.routers.integrations_gcal.get_google_calendar_service", return_value=svc):
        resp = recruiter_client.get("/api/v2/integrations/google-calendar/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


def test_status_connected(recruiter_client):
    svc = MagicMock()
    svc.get_connection = AsyncMock(return_value={
        "provider_email": "rec@m.ai", "created_at": "2025-01-01T00:00:00+00:00",
        "calendar_watch_enabled": True, "auto_join_untracked": True,
    })
    with patch("app.api.v2.routers.integrations_gcal.get_google_calendar_service", return_value=svc):
        resp = recruiter_client.get("/api/v2/integrations/google-calendar/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["email"] == "rec@m.ai"
    assert body["auto_join_untracked"] is True


# ----------------------- toggles -----------------------

def _override_supabase(result_data):
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("update", "eq"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=result_data))
    sb.table = MagicMock(return_value=builder)
    app.dependency_overrides[get_supabase] = lambda: sb
    return sb


def test_calendar_watch_toggle_ok(recruiter_client):
    _override_supabase([{"id": "conn1"}])
    try:
        resp = recruiter_client.patch(
            "/api/v2/integrations/google-calendar/calendar-watch", json={"enabled": False}
        )
    finally:
        app.dependency_overrides.pop(get_supabase, None)
    assert resp.status_code == 200
    assert resp.json()["calendar_watch_enabled"] is False


def test_calendar_watch_toggle_not_found(recruiter_client):
    _override_supabase([])
    try:
        resp = recruiter_client.patch(
            "/api/v2/integrations/google-calendar/calendar-watch", json={"enabled": True}
        )
    finally:
        app.dependency_overrides.pop(get_supabase, None)
    assert resp.status_code == 404


def test_auto_join_toggle_ok(recruiter_client):
    _override_supabase([{"id": "conn1"}])
    try:
        resp = recruiter_client.patch(
            "/api/v2/integrations/google-calendar/auto-join-untracked", json={"enabled": True}
        )
    finally:
        app.dependency_overrides.pop(get_supabase, None)
    assert resp.status_code == 200
    assert resp.json()["auto_join_untracked"] is True


def test_auto_join_toggle_missing_column_503(recruiter_client):
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("update", "eq"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(side_effect=RuntimeError("column auto_join_untracked does not exist in schema cache"))
    sb.table = MagicMock(return_value=builder)
    app.dependency_overrides[get_supabase] = lambda: sb
    try:
        resp = recruiter_client.patch(
            "/api/v2/integrations/google-calendar/auto-join-untracked", json={"enabled": True}
        )
    finally:
        app.dependency_overrides.pop(get_supabase, None)
    assert resp.status_code == 503


def test_auto_join_toggle_not_found(recruiter_client):
    _override_supabase([])
    try:
        resp = recruiter_client.patch(
            "/api/v2/integrations/google-calendar/auto-join-untracked", json={"enabled": True}
        )
    finally:
        app.dependency_overrides.pop(get_supabase, None)
    assert resp.status_code == 404


# ----------------------- disconnect -----------------------

def test_disconnect_ok(recruiter_client):
    svc = MagicMock()
    svc.disconnect = AsyncMock(return_value={"status": "disconnected"})
    with patch("app.api.v2.routers.integrations_gcal.get_google_calendar_service", return_value=svc):
        resp = recruiter_client.delete("/api/v2/integrations/google-calendar/disconnect")
    assert resp.status_code == 200
    assert resp.json()["status"] == "disconnected"


def test_disconnect_failure_503(recruiter_client):
    svc = MagicMock()
    svc.disconnect = AsyncMock(side_effect=RuntimeError("recall error"))
    with patch("app.api.v2.routers.integrations_gcal.get_google_calendar_service", return_value=svc):
        resp = recruiter_client.delete("/api/v2/integrations/google-calendar/disconnect")
    assert resp.status_code == 503


# ----------------------- callback (no auth) -----------------------

def test_callback_denied(unauthed_client):
    resp = unauthed_client.get(
        "/api/v2/integrations/google-calendar/callback?error=access_denied", follow_redirects=False
    )
    assert "google_calendar=error" in resp.headers["location"]


def test_callback_missing_params(unauthed_client):
    resp = unauthed_client.get(
        "/api/v2/integrations/google-calendar/callback", follow_redirects=False
    )
    assert "missing_params" in resp.headers["location"]


def test_callback_bad_state(unauthed_client):
    svc = MagicMock()
    svc.verify_oauth_state = MagicMock(side_effect=ValueError("bad"))
    with patch("app.api.v2.routers.integrations_gcal.get_google_calendar_service", return_value=svc):
        resp = unauthed_client.get(
            "/api/v2/integrations/google-calendar/callback?code=c&state=s", follow_redirects=False
        )
    assert "invalid_state" in resp.headers["location"]


def test_callback_exchange_failure(unauthed_client):
    svc = MagicMock()
    svc.verify_oauth_state = MagicMock(return_value={"user_id": "u1", "org_id": "o1"})
    svc.exchange_code = AsyncMock(side_effect=ValueError("bad code"))
    with patch("app.api.v2.routers.integrations_gcal.get_google_calendar_service", return_value=svc):
        resp = unauthed_client.get(
            "/api/v2/integrations/google-calendar/callback?code=c&state=s", follow_redirects=False
        )
    assert "exchange_failed" in resp.headers["location"]


def test_callback_no_email(unauthed_client):
    svc = MagicMock()
    svc.verify_oauth_state = MagicMock(return_value={"user_id": "u1", "org_id": "o1"})
    svc.exchange_code = AsyncMock(return_value={"access_token": "at"})
    svc.get_userinfo = AsyncMock(return_value={"email": ""})
    with patch("app.api.v2.routers.integrations_gcal.get_google_calendar_service", return_value=svc):
        resp = unauthed_client.get(
            "/api/v2/integrations/google-calendar/callback?code=c&state=s", follow_redirects=False
        )
    assert "no_email" in resp.headers["location"]


def test_callback_success_saves_and_registers(unauthed_client):
    svc = MagicMock()
    svc.verify_oauth_state = MagicMock(return_value={"user_id": "u1", "org_id": "o1"})
    svc.exchange_code = AsyncMock(return_value={"access_token": "at"})
    svc.get_userinfo = AsyncMock(return_value={"email": "rec@m.ai"})
    svc.save_connection = AsyncMock()
    svc.register_with_recall = AsyncMock()
    with patch("app.api.v2.routers.integrations_gcal.get_google_calendar_service", return_value=svc):
        resp = unauthed_client.get(
            "/api/v2/integrations/google-calendar/callback?code=c&state=s", follow_redirects=False
        )
    assert "google_calendar=connected" in resp.headers["location"]
    svc.save_connection.assert_awaited_once()
    svc.register_with_recall.assert_awaited_once()


def test_callback_recall_registration_failure_still_connects(unauthed_client):
    svc = MagicMock()
    svc.verify_oauth_state = MagicMock(return_value={"user_id": "u1", "org_id": "o1"})
    svc.exchange_code = AsyncMock(return_value={"access_token": "at"})
    svc.get_userinfo = AsyncMock(return_value={"email": "rec@m.ai"})
    svc.save_connection = AsyncMock()
    svc.register_with_recall = AsyncMock(side_effect=RuntimeError("recall down"))
    with patch("app.api.v2.routers.integrations_gcal.get_google_calendar_service", return_value=svc):
        resp = unauthed_client.get(
            "/api/v2/integrations/google-calendar/callback?code=c&state=s", follow_redirects=False
        )
    assert "google_calendar=connected" in resp.headers["location"]
