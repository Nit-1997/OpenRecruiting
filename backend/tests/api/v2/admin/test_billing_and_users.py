"""BE-T1: admin billing + users router coverage (beyond the seat-limit and
reset-invite tests in the sibling files)."""
import httpx
import pytest

import app.api.v2.routers.admin.billing as billing_router
from tests.helpers.supabase_mocks import rest_url, auth_url
from tests.helpers.mock_data import (
    ORG_ID,
    ORG_2_ID,
    RECRUITER_USER_ID,
    NOW,
    make_profile,
)

V2_ROOT = "/api/v2"
ADMIN = f"{V2_ROOT}/admin"
SUB_ID = "00000000-0000-0000-0000-0000000000b1"


class _FakeBillingService:
    def __init__(self, plan=None):
        self._plan = plan or {
            "id": "00000000-0000-0000-0000-0000000000b9",
            "display_name": "Enterprise",
            "name": "enterprise",
            "intake_credits": 100,
            "interview_credits": 100,
        }

    async def get_plan_by_name(self, name):
        return self._plan

    async def cancel_subscription(self, org_id):
        return None


def _sub_row():
    return {
        "id": SUB_ID,
        "organization_id": ORG_ID,
        "plan_id": "00000000-0000-0000-0000-0000000000b9",
        "status": "active",
        "is_manual": True,
        "plans": {"name": "enterprise", "display_name": "Enterprise"},
        "organizations": {"name": "Acme"},
    }


# ── billing ──────────────────────────────────────────────────────────────────

def test_list_subscriptions(staff_client, respx_mock):
    respx_mock.get(rest_url("subscriptions")).mock(
        return_value=httpx.Response(200, json=[_sub_row()])
    )
    resp = staff_client.get(f"{ADMIN}/billing/subscriptions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body[0]["plan_name"] == "enterprise"
    assert body[0]["org_name"] == "Acme"


def test_create_manual_subscription(staff_client, respx_mock, monkeypatch):
    monkeypatch.setattr(billing_router, "get_billing_service", lambda: _FakeBillingService())
    respx_mock.patch(rest_url("subscriptions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.post(rest_url("subscriptions")).mock(
        return_value=httpx.Response(201, json=[_sub_row()])
    )
    respx_mock.patch(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("usage_credits")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.post(rest_url("usage_credits")).mock(
        return_value=httpx.Response(201, json=[])
    )
    resp = staff_client.post(
        f"{ADMIN}/billing/subscriptions",
        json={"organization_id": ORG_ID, "plan_name": "enterprise"},
    )
    assert resp.status_code == 201, resp.text


def test_delete_subscription(staff_client, respx_mock):
    respx_mock.patch(rest_url("subscriptions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.delete(f"{ADMIN}/billing/subscriptions/{SUB_ID}")
    assert resp.status_code == 200, resp.text


def test_get_organization_credits(staff_client, respx_mock):
    respx_mock.get(rest_url("usage_credits")).mock(
        return_value=httpx.Response(
            200,
            json=[{"credit_type": "intake", "total": 100, "used": 10, "period_start": NOW}],
        )
    )
    respx_mock.get(rest_url("topup_credits")).mock(
        return_value=httpx.Response(200, json=[{"credit_type": "intake", "remaining": 5}])
    )
    resp = staff_client.get(f"{ADMIN}/billing/organizations/{ORG_ID}/credits")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["credits"][0]["monthly_remaining"] == 90
    assert body["credits"][0]["effective_remaining"] == 95


def test_migrate_user_target_org_404(staff_client, respx_mock):
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.post(
        f"{ADMIN}/billing/organizations/{ORG_ID}/migrate-user",
        json={"user_id": RECRUITER_USER_ID, "cancel_existing_subscription": False},
    )
    assert resp.status_code == 404, resp.text


def test_migrate_user_not_enterprise_400(staff_client, respx_mock):
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[{"id": ORG_ID, "org_type": "personal", "name": "P"}])
    )
    resp = staff_client.post(
        f"{ADMIN}/billing/organizations/{ORG_ID}/migrate-user",
        json={"user_id": RECRUITER_USER_ID, "cancel_existing_subscription": False},
    )
    assert resp.status_code == 400, resp.text


def test_migrate_user_already_in_org_409(staff_client, respx_mock):
    def _orgs(_request):
        return httpx.Response(200, json=[{"id": ORG_ID, "org_type": "enterprise", "name": "E"}])

    def _profiles(_request):
        return httpx.Response(
            200, json=[{"id": RECRUITER_USER_ID, "email": "u@t.com", "organization_id": ORG_ID}]
        )

    respx_mock.get(rest_url("organizations")).mock(side_effect=_orgs)
    respx_mock.get(rest_url("profiles")).mock(side_effect=_profiles)
    resp = staff_client.post(
        f"{ADMIN}/billing/organizations/{ORG_ID}/migrate-user",
        json={"user_id": RECRUITER_USER_ID, "cancel_existing_subscription": False},
    )
    assert resp.status_code == 409, resp.text


# ── users: list_organization_users + create + resend ─────────────────────────

def test_list_organization_users(staff_client, respx_mock):
    def _profiles(request):
        if request.headers.get("Prefer") == "count=exact":
            return httpx.Response(200, headers={"content-range": "0-0/1"}, json=[])
        return httpx.Response(200, json=[make_profile()])

    respx_mock.get(rest_url("profiles")).mock(side_effect=_profiles)
    respx_mock.get(
        url__regex=r"http://test-supabase.local/auth/v1/admin/users/.*"
    ).mock(return_value=httpx.Response(200, json={"email_confirmed_at": NOW, "last_sign_in_at": NOW}))

    resp = staff_client.get(f"{ADMIN}/organizations/{ORG_ID}/users")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1


def test_create_user_with_magic_link_conflict(staff_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[{"id": "x"}])
    )
    resp = staff_client.post(
        f"{ADMIN}/organizations/{ORG_ID}/users",
        json={"email": "new@t.com", "full_name": "New User"},
    )
    assert resp.status_code == 409, resp.text


def test_create_user_with_magic_link_success(staff_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.post(auth_url("/invite")).mock(
        return_value=httpx.Response(200, json={"id": RECRUITER_USER_ID})
    )
    respx_mock.post(rest_url("profiles")).mock(
        return_value=httpx.Response(201, json=[make_profile(user_id=RECRUITER_USER_ID)])
    )
    resp = staff_client.post(
        f"{ADMIN}/organizations/{ORG_ID}/users",
        json={"email": "new@t.com", "full_name": "New User"},
    )
    assert resp.status_code == 201, resp.text


def test_resend_magic_link_404(staff_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.post(
        f"{ADMIN}/users/resend-magic-link", json={"email": "missing@t.com"}
    )
    assert resp.status_code == 404, resp.text


def test_resend_magic_link_success(staff_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[{"id": RECRUITER_USER_ID, "email": "u@t.com"}])
    )
    respx_mock.post(auth_url("/invite")).mock(
        return_value=httpx.Response(200, json={"id": RECRUITER_USER_ID})
    )
    resp = staff_client.post(
        f"{ADMIN}/users/resend-magic-link", json={"email": "u@t.com"}
    )
    assert resp.status_code == 200, resp.text
