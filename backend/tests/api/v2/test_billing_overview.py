"""Tests for GET /api/v2/billing/overview.

Uses the recruiter_client (org-scoped) + a respx-mocked supabase REST so the
single `usage_credits` read resolves. There are no plans, subscriptions or
top-ups — the org's credit budget is the whole response.
"""

from tests.helpers.supabase_mocks import mock_select

ENDPOINT = "/api/v2/billing/overview"


def test_overview_returns_org_credit_budget(recruiter_client, respx_mock):
    mock_select(respx_mock, "usage_credits", [
        {"credit_type": "intake", "total": 100, "used": 20},
        {"credit_type": "interview", "total": 50, "used": 5},
    ])

    resp = recruiter_client.get(ENDPOINT)
    assert resp.status_code == 200
    assert resp.json() == {
        "intake_total": 100,
        "intake_used": 20,
        "interview_total": 50,
        "interview_used": 5,
    }


def test_overview_carries_no_plan_subscription_or_topup_fields(recruiter_client, respx_mock):
    """The payment layer is gone — none of its fields may resurface."""
    mock_select(respx_mock, "usage_credits", [
        {"credit_type": "intake", "total": 10, "used": 0},
    ])

    body = recruiter_client.get(ENDPOINT).json()
    for gone in (
        "plan_name",
        "plan_display_name",
        "subscription_status",
        "period_start",
        "period_end",
        "cancel_at_period_end",
        "intake_topup",
        "interview_topup",
    ):
        assert gone not in body


def test_overview_unprovisioned_org_defaults_to_zero(recruiter_client, respx_mock):
    mock_select(respx_mock, "usage_credits", [])

    body = recruiter_client.get(ENDPOINT).json()
    assert body["intake_total"] == 0
    assert body["intake_used"] == 0
    assert body["interview_total"] == 0
    assert body["interview_used"] == 0


def test_overview_passes_through_unlimited_sentinel(recruiter_client, respx_mock):
    mock_select(respx_mock, "usage_credits", [
        {"credit_type": "interview", "total": -1, "used": 7},
    ])

    body = recruiter_client.get(ENDPOINT).json()
    assert body["interview_total"] == -1
    assert body["interview_used"] == 7


def test_overview_requires_auth(unauthed_client):
    resp = unauthed_client.get(ENDPOINT)
    assert resp.status_code in (401, 403)
