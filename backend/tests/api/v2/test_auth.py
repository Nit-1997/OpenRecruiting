"""
Tests for v2 auth endpoints.

Covers `GET /api/v2/auth/me`. The frontend authenticates against Supabase
directly via `@supabase/supabase-js`; the v2 backend only verifies the bearer
JWT and exposes this profile-join helper.
"""

from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user, CurrentUser
from tests.helpers.mock_data import (
    ORG_ID,
    RECRUITER_USER_ID,
    RECRUITER_EMAIL,
)
from tests.helpers.supabase_mocks import rest_url


V2_AUTH = "/api/v2/auth"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_org_user_client():
    no_org_user = CurrentUser(
        id=UUID(RECRUITER_USER_ID),
        email=RECRUITER_EMAIL,
        is_staff=False,
        organization_id=None,
    )
    app.dependency_overrides[get_current_user] = lambda: no_org_user
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


def test_me_200_returns_user_with_joined_name(recruiter_client, respx_mock):
    # Profile lookup returns the joined full_name.
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[{"full_name": "Test Recruiter"}])
    )
    # /me also queries organization_invites for the has_pending_invite flag.
    respx_mock.get(rest_url("organization_invites")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = recruiter_client.get(f"{V2_AUTH}/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == RECRUITER_USER_ID
    assert body["email"] == RECRUITER_EMAIL
    assert body["organization_id"] == ORG_ID
    assert body["is_staff"] is False
    assert body["name"] == "Test Recruiter"


def test_me_200_with_null_name_when_profile_missing_full_name(recruiter_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[{"full_name": None}])
    )
    respx_mock.get(rest_url("organization_invites")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.get(f"{V2_AUTH}/me")
    assert resp.status_code == 200
    assert resp.json()["name"] is None


def test_me_401_without_auth_header(unauthed_client, respx_mock):
    resp = unauthed_client.get(f"{V2_AUTH}/me")
    # No bearer -> HTTPBearer raises 403/401. FastAPI's HTTPBearer default
    # status is 403 for missing creds; either way it's NOT 200.
    assert resp.status_code in (401, 403)


def test_me_403_when_user_has_no_org(respx_mock):
    """Decision: /me requires org. Users without an org get 403 + standard body."""
    with _no_org_user_client() as client:
        resp = client.get(f"{V2_AUTH}/me")
    assert resp.status_code == 403
    assert "organization" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /auth/complete-signup — error-message leakage
# ---------------------------------------------------------------------------


def test_complete_signup_500_returns_static_message_no_raw_exception(monkeypatch):
    """A non-Value/non-SignupBlocked exception must NOT leak raw exception text
    to the client. The handler logs the detail server-side and returns a static
    500 message."""
    from unittest.mock import AsyncMock

    import app.api.v2.routers.auth as auth_router
    from app.dependencies import get_authenticated_user_id

    secret_leak = "psql://user:HUNTER2@db.internal:5432 connection refused"

    monkeypatch.setattr(
        auth_router,
        "complete_user_signup",
        AsyncMock(side_effect=RuntimeError(secret_leak)),
    )
    app.dependency_overrides[get_authenticated_user_id] = lambda: RECRUITER_USER_ID

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(f"{V2_AUTH}/complete-signup")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert secret_leak not in str(detail)
    assert "HUNTER2" not in str(detail)
