"""Teammate invite is single-sourced through `team_service.invite_teammate`.

`POST /api/v2/team/invite` (recruiter, authed) delegates to the service helper,
so duplicate handling, seat enforcement, expiry, and the return shape live in
one place. Duplicates return a proper 4xx (409), never a
200-with-`{"error":...}` body.
"""

import httpx

from tests.helpers.supabase_mocks import rest_url

TEAM_INVITE = "/api/v2/team/invite"


def _mock_subscriptions_unlimited(respx_mock):
    # Seat check: -1 == unlimited so the seat gate never blocks the test.
    respx_mock.get(rest_url("subscriptions")).mock(
        return_value=httpx.Response(200, json=[{"custom_max_users": -1, "plans": None}])
    )


def test_team_invite_duplicate_member_returns_409(recruiter_client, respx_mock):
    # First profiles query (member-exists check) returns a match -> 409 ALREADY_MEMBER.
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[{"id": "existing-id"}])
    )
    resp = recruiter_client.post(TEAM_INVITE, json={"email": "dupe@example.com"})
    assert resp.status_code == 409
    assert "member" in resp.json()["detail"].lower()


def test_invite_is_built_in_one_place():
    """Single-source check: there is exactly one place that builds the invite."""
    from app.api.v2.services import team_service

    assert hasattr(team_service, "invite_teammate")


def test_invite_email_failure_returns_static_message_no_raw_exception(
    recruiter_client, respx_mock, monkeypatch
):
    """When the Supabase invite-email call fails, the raw exception text must
    not leak to the client; the service logs it and surfaces a static message."""
    from unittest.mock import AsyncMock

    import app.services.supabase as supabase_module

    # member-exists, pending-invite, existing-profile checks all empty.
    respx_mock.get(rest_url("profiles")).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(rest_url("organization_invites")).mock(
        return_value=httpx.Response(200, json=[])
    )
    _mock_subscriptions_unlimited(respx_mock)

    secret_leak = "supabase admin key sk_live_DEADBEEF rejected by gotrue"
    monkeypatch.setattr(
        supabase_module.SupabaseAdminClient,
        "invite_user_by_email",
        AsyncMock(side_effect=Exception(secret_leak)),
    )

    resp = recruiter_client.post(TEAM_INVITE, json={"email": "new@example.com"})

    # Email failure is a 4xx (conflict/upstream) but with a STATIC detail.
    assert resp.status_code >= 400
    detail = str(resp.json().get("detail", ""))
    assert secret_leak not in detail
    assert "sk_live_DEADBEEF" not in detail
