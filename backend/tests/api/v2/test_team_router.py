"""Tests for /api/v2/team/* routes and the avatar helpers.

get_team / accept-invite / cancel-invite / remove-member run under recruiter
auth with respx-mocked supabase REST. respx routes by URL (table), returning
the same body for repeated reads of a table — fine for these handlers.
"""

import respx

from app.api.v2.routers.team import _avatar_color, _avatar_initials
from tests.helpers.mock_data import RECRUITER_USER_ID
from tests.helpers.supabase_mocks import mock_select, mock_update, mock_insert


# ----------------------- avatar helpers -----------------------

def test_avatar_color_is_deterministic_and_in_palette():
    c1 = _avatar_color("abc")
    c2 = _avatar_color("abc")
    assert c1 == c2
    assert c1.startswith("#")


def test_avatar_initials_two_part_name():
    assert _avatar_initials("Alice Smith", "a@b.com") == "AS"


def test_avatar_initials_single_name():
    assert _avatar_initials("Alice", "a@b.com") == "AL"


def test_avatar_initials_falls_back_to_email():
    assert _avatar_initials("", "bob@b.com") == "BO"
    assert _avatar_initials(None, "carol@b.com") == "CA"


# ----------------------- get_team -----------------------

def test_get_team_overview(recruiter_client, respx_mock):
    mock_select(respx_mock, "organizations", [{"name": "Acme Inc"}])
    mock_select(respx_mock, "profiles", [
        {"id": RECRUITER_USER_ID, "email": "owner@m.ai", "full_name": "Owner One", "created_at": "2025-01-01T00:00:00+00:00"},
        {"id": "p2", "email": "rec@m.ai", "full_name": "Rec Two", "created_at": "2025-01-02T00:00:00+00:00"},
    ])
    mock_select(respx_mock, "organization_invites", [
        {"id": "inv1", "email": "pending@m.ai", "invited_by": RECRUITER_USER_ID, "status": "pending",
         "created_at": "2025-01-03T00:00:00+00:00", "expires_at": "2025-01-17T00:00:00+00:00"},
    ])
    mock_select(respx_mock, "subscriptions", [{"custom_max_users": 5, "plans": {"max_users": 3}}])

    resp = recruiter_client.get("/api/v2/team")
    assert resp.status_code == 200
    body = resp.json()
    assert body["organization_name"] == "Acme Inc"
    assert len(body["members"]) == 2
    assert body["members"][0]["role"] == "owner"
    assert body["members"][1]["role"] == "recruiter"
    assert body["seat_usage"]["used"] == 2
    assert body["seat_usage"]["total"] == 5  # custom_max_users wins
    assert len(body["pending_invites"]) == 1


def test_get_team_seat_limit_falls_back_to_plan(recruiter_client, respx_mock):
    mock_select(respx_mock, "organizations", [{"name": "Acme"}])
    mock_select(respx_mock, "profiles", [])
    mock_select(respx_mock, "organization_invites", [])
    mock_select(respx_mock, "subscriptions", [{"custom_max_users": None, "plans": {"max_users": 7}}])
    resp = recruiter_client.get("/api/v2/team")
    assert resp.status_code == 200
    assert resp.json()["seat_usage"]["total"] == 7


def test_get_team_no_subscription_defaults_to_one_seat(recruiter_client, respx_mock):
    mock_select(respx_mock, "organizations", [{"name": "Acme"}])
    mock_select(respx_mock, "profiles", [])
    mock_select(respx_mock, "organization_invites", [])
    mock_select(respx_mock, "subscriptions", [])
    resp = recruiter_client.get("/api/v2/team")
    assert resp.status_code == 200
    assert resp.json()["seat_usage"]["total"] == 1


# ----------------------- accept-invite -----------------------

def test_accept_invite_no_pending_is_noop(recruiter_client, respx_mock):
    mock_select(respx_mock, "organization_invites", [])
    resp = recruiter_client.post("/api/v2/team/accept-invite")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_accept_invite_marks_accepted(recruiter_client, respx_mock):
    mock_select(respx_mock, "organization_invites", [{"id": "inv1"}])
    mock_update(respx_mock, "organization_invites", {"id": "inv1"})
    mock_update(respx_mock, "profiles", {"id": RECRUITER_USER_ID})
    resp = recruiter_client.post("/api/v2/team/accept-invite")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ----------------------- cancel-invite -----------------------

def test_cancel_invite_not_found(recruiter_client, respx_mock):
    mock_select(respx_mock, "organization_invites", [])
    resp = recruiter_client.delete("/api/v2/team/invites/00000000-0000-0000-0000-0000000000ff")
    assert resp.status_code == 404


# ----------------------- remove-member -----------------------

def test_remove_self_forbidden(recruiter_client, respx_mock):
    resp = recruiter_client.delete(f"/api/v2/team/members/{RECRUITER_USER_ID}")
    assert resp.status_code == 403


def test_remove_member_not_found(recruiter_client, respx_mock):
    mock_select(respx_mock, "profiles", [])
    resp = recruiter_client.delete("/api/v2/team/members/00000000-0000-0000-0000-0000000000ee")
    assert resp.status_code == 404
