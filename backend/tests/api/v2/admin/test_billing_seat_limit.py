"""Seat-limit checks in admin billing migrate-user (BE-P0-1).

These pin that the member-count seat gate uses count_async() (which reads the
PostgREST content-range header) and never raises a 500 from the previously
broken .select("id", count="exact") + .count pattern.
"""
import httpx

from tests.helpers.supabase_mocks import rest_url
from tests.helpers.mock_data import ORG_ID, ORG_2_ID, RECRUITER_USER_ID

V2_ROOT = "/api/v2"
TARGET_ORG = ORG_ID
SOURCE_ORG = ORG_2_ID
SEAT_LIMIT = 5


def _org_row(org_id=TARGET_ORG, org_type="enterprise"):
    return {"id": org_id, "org_type": org_type, "name": "Enterprise Co"}


def _profile_row(user_id=RECRUITER_USER_ID, org_id=SOURCE_ORG):
    return {"id": user_id, "email": "mover@test.com", "organization_id": org_id}


def _active_sub_row(max_users=SEAT_LIMIT):
    return {
        "custom_max_users": max_users,
        "plan_id": "plan-1",
        "plans": {"max_users": max_users},
        "status": "active",
    }


def test_migrate_user_seat_limit_reached_returns_403_not_500(staff_client, respx_mock):
    """Target org already at max_users -> 403, NOT a 500/TypeError from count."""

    def _organizations(_request):
        return httpx.Response(200, json=[_org_row()])

    def _profiles(request):
        # The seat-gate query asks for a count via the content-range header.
        if request.headers.get("Prefer") == "count=exact":
            return httpx.Response(
                200,
                headers={"content-range": f"0-0/{SEAT_LIMIT}"},
                json=[],
            )
        return httpx.Response(200, json=[_profile_row()])

    def _subscriptions(_request):
        return httpx.Response(200, json=[_active_sub_row(SEAT_LIMIT)])

    respx_mock.get(rest_url("organizations")).mock(side_effect=_organizations)
    respx_mock.get(rest_url("profiles")).mock(side_effect=_profiles)
    respx_mock.get(rest_url("subscriptions")).mock(side_effect=_subscriptions)

    resp = staff_client.post(
        f"{V2_ROOT}/admin/billing/organizations/{TARGET_ORG}/migrate-user",
        json={"user_id": RECRUITER_USER_ID, "cancel_existing_subscription": False},
    )

    assert resp.status_code == 403, resp.text
    assert "maximum seats" in resp.text


def test_migrate_user_under_seat_limit_proceeds(staff_client, respx_mock):
    """Under the seat cap the migration proceeds cleanly (no 500)."""

    def _organizations(_request):
        return httpx.Response(200, json=[_org_row()])

    def _profiles(request):
        if request.headers.get("Prefer") == "count=exact":
            # Seat-gate count for the target org: under the limit.
            return httpx.Response(
                200,
                headers={"content-range": "0-0/1"},
                json=[],
            )
        return httpx.Response(200, json=[_profile_row()])

    def _subscriptions(_request):
        return httpx.Response(200, json=[_active_sub_row(SEAT_LIMIT)])

    respx_mock.get(rest_url("organizations")).mock(side_effect=_organizations)
    respx_mock.get(rest_url("profiles")).mock(side_effect=_profiles)
    respx_mock.patch(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[_profile_row(org_id=TARGET_ORG)])
    )
    respx_mock.patch(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.patch(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("subscriptions")).mock(side_effect=_subscriptions)

    resp = staff_client.post(
        f"{V2_ROOT}/admin/billing/organizations/{TARGET_ORG}/migrate-user",
        json={"user_id": RECRUITER_USER_ID, "cancel_existing_subscription": False},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_id"] == RECRUITER_USER_ID
    assert body["target_org_id"] == TARGET_ORG
