"""Tests for GET /api/v2/billing/overview.

Uses the recruiter_client (org-scoped) + respx-mocked supabase REST so the three
table reads (subscriptions, usage_credits, topup_credits) resolve. Covers the
populated path, the no-subscription/no-credits path, and topup aggregation.
"""

from tests.helpers.supabase_mocks import mock_select

ENDPOINT = "/api/v2/billing/overview"


def test_overview_with_active_subscription_and_credits(recruiter_client, respx_mock):
    mock_select(respx_mock, "subscriptions", [{
        "status": "active",
        "current_period_start": "2025-01-01T00:00:00+00:00",
        "current_period_end": "2025-02-01T00:00:00+00:00",
        "cancel_at_period_end": False,
        "plans": {"name": "pro", "display_name": "Pro Plan"},
    }])
    mock_select(respx_mock, "usage_credits", [
        {"credit_type": "intake", "total": 100, "used": 20},
        {"credit_type": "interview", "total": 50, "used": 5},
    ])
    mock_select(respx_mock, "topup_credits", [
        {"credit_type": "intake", "remaining": 10},
        {"credit_type": "intake", "remaining": 5},
        {"credit_type": "interview", "remaining": 3},
    ])

    resp = recruiter_client.get(ENDPOINT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_name"] == "pro"
    assert body["plan_display_name"] == "Pro Plan"
    assert body["subscription_status"] == "active"
    assert body["intake_total"] == 100
    assert body["intake_used"] == 20
    assert body["intake_topup"] == 15  # 10 + 5 aggregated
    assert body["interview_total"] == 50
    assert body["interview_topup"] == 3


def test_overview_no_subscription_defaults(recruiter_client, respx_mock):
    mock_select(respx_mock, "subscriptions", [])
    mock_select(respx_mock, "usage_credits", [])
    mock_select(respx_mock, "topup_credits", [])

    resp = recruiter_client.get(ENDPOINT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_name"] == "Custom"
    assert body["plan_display_name"] == "Custom"
    assert body["subscription_status"] == "none"
    assert body["cancel_at_period_end"] is False
    assert body["intake_total"] == 0
    assert body["interview_topup"] == 0


def test_overview_plan_without_display_name(recruiter_client, respx_mock):
    mock_select(respx_mock, "subscriptions", [{
        "status": "active",
        "current_period_start": None,
        "current_period_end": None,
        "cancel_at_period_end": True,
        "plans": {"name": "starter"},
    }])
    mock_select(respx_mock, "usage_credits", [])
    mock_select(respx_mock, "topup_credits", [])

    resp = recruiter_client.get(ENDPOINT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_name"] == "starter"
    assert body["plan_display_name"] == "starter"  # falls back to name
    assert body["cancel_at_period_end"] is True


def test_overview_requires_auth(unauthed_client):
    resp = unauthed_client.get(ENDPOINT)
    assert resp.status_code in (401, 403)
