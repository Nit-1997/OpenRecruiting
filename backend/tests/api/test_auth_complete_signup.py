from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies import get_authenticated_user_id
from app.services.signup_service import SignupBlockedError

client = TestClient(app)


def test_complete_signup_route_mounted_requires_auth():
    # 401/403 (not 404) proves the route exists and the JWT guard fires.
    resp = client.post("/api/v2/auth/complete-signup")
    assert resp.status_code in (401, 403), resp.status_code


def test_complete_signup_blocked_returns_structured_403_and_cleans_up():
    # Pins the load-bearing 403 contract: SignupBlockedError (a ValueError
    # subclass) must hit its own except BEFORE the except ValueError -> 400, the
    # body must be the structured {"message","code"} shape, and best-effort
    # orphan cleanup (delete_user) must be awaited.
    delete_user = AsyncMock()
    admin_client = MagicMock()
    admin_client.delete_user = delete_user

    app.dependency_overrides[get_authenticated_user_id] = lambda: "u1"
    try:
        with patch(
            "app.api.v2.routers.auth.complete_user_signup",
            new=AsyncMock(side_effect=SignupBlockedError("blocked")),
        ), patch(
            "app.api.v2.routers.auth.get_supabase_admin_client",
            return_value=admin_client,
        ):
            resp = client.post("/api/v2/auth/complete-signup")
    finally:
        app.dependency_overrides.pop(get_authenticated_user_id, None)

    assert resp.status_code == 403, resp.status_code
    assert resp.json()["detail"] == {"message": "blocked", "code": "signup_blocked"}
    delete_user.assert_awaited_once_with("u1")


def test_complete_onboarding_route_mounted_requires_auth():
    # 401/403 (not 404) proves the route exists and the JWT guard fires.
    resp = client.post("/api/v2/auth/complete-onboarding")
    assert resp.status_code in (401, 403), resp.status_code


def _onboarding_admin_client(rows):
    builder = MagicMock()
    builder.update.return_value = builder
    builder.eq.return_value = builder
    builder.execute_async = AsyncMock(return_value=MagicMock(data=rows))
    admin_client = MagicMock()
    admin_client.table.return_value = builder
    return admin_client, builder


def test_complete_onboarding_sets_flag_and_returns_ok():
    admin_client, builder = _onboarding_admin_client(
        [{"id": "u1", "onboarding_completed": True}]
    )
    app.dependency_overrides[get_authenticated_user_id] = lambda: "u1"
    try:
        with patch(
            "app.api.v2.routers.auth.get_supabase_admin_client",
            return_value=admin_client,
        ):
            resp = client.post("/api/v2/auth/complete-onboarding")
    finally:
        app.dependency_overrides.pop(get_authenticated_user_id, None)

    assert resp.status_code == 200, resp.status_code
    assert resp.json() == {"onboarding_completed": True}
    admin_client.table.assert_called_once_with("profiles")
    builder.update.assert_called_once_with({"onboarding_completed": True})
    builder.eq.assert_called_once_with("id", "u1")


def test_complete_onboarding_missing_profile_returns_404():
    admin_client, _ = _onboarding_admin_client([])
    app.dependency_overrides[get_authenticated_user_id] = lambda: "u1"
    try:
        with patch(
            "app.api.v2.routers.auth.get_supabase_admin_client",
            return_value=admin_client,
        ):
            resp = client.post("/api/v2/auth/complete-onboarding")
    finally:
        app.dependency_overrides.pop(get_authenticated_user_id, None)

    assert resp.status_code == 404, resp.status_code
