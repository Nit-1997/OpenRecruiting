"""Covers PUT /api/v2/admin/billing/subscriptions/{sub_id}
(update_manual_subscription) — the largest uncovered admin/billing route."""

import httpx

import app.api.v2.routers.admin.billing as billing_router
from tests.helpers.supabase_mocks import rest_url
from tests.helpers.mock_data import ORG_ID

ADMIN = "/api/v2/admin"
SUB_ID = "00000000-0000-0000-0000-0000000000b1"


class _FakeBillingService:
    async def get_plan_by_name(self, name):
        return {
            "id": "00000000-0000-0000-0000-0000000000b9",
            "display_name": "Enterprise", "name": "enterprise",
            "intake_credits": 100, "interview_credits": 100,
        }


def _sub_row():
    return {
        "id": SUB_ID, "organization_id": ORG_ID, "plan_id": "00000000-0000-0000-0000-0000000000b9",
        "status": "active", "is_manual": True,
        "plans": {"name": "enterprise", "display_name": "Enterprise"},
        "organizations": {"name": "Acme"},
    }


def test_update_subscription_with_plan_change(staff_client, respx_mock, monkeypatch):
    monkeypatch.setattr(billing_router, "get_billing_service", lambda: _FakeBillingService())
    respx_mock.patch(rest_url("subscriptions")).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(rest_url("subscriptions")).mock(return_value=httpx.Response(200, json=[_sub_row()]))
    respx_mock.patch(rest_url("organizations")).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(rest_url("usage_credits")).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.post(rest_url("usage_credits")).mock(return_value=httpx.Response(201, json=[]))

    resp = staff_client.put(
        f"{ADMIN}/billing/subscriptions/{SUB_ID}",
        json={"plan_name": "enterprise", "custom_intake_credits": 250, "custom_max_users": 10},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan_name"] == "enterprise"


def test_update_subscription_status_only(staff_client, respx_mock):
    # No plan/credit change -> the credits_changed branch is skipped.
    respx_mock.patch(rest_url("subscriptions")).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(rest_url("subscriptions")).mock(return_value=httpx.Response(200, json=[_sub_row()]))

    resp = staff_client.put(
        f"{ADMIN}/billing/subscriptions/{SUB_ID}",
        json={"status": "cancelled"},
    )
    assert resp.status_code == 200, resp.text


def test_update_subscription_not_found_404(staff_client, respx_mock):
    respx_mock.patch(rest_url("subscriptions")).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(rest_url("subscriptions")).mock(return_value=httpx.Response(200, json=[]))

    resp = staff_client.put(
        f"{ADMIN}/billing/subscriptions/{SUB_ID}",
        json={"custom_price_dollars": 99.0},
    )
    assert resp.status_code == 404
