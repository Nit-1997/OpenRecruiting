"""Tests for GET /api/v2/billing/overview.

Uses the recruiter_client (org-scoped) + respx-mocked supabase REST so the two
table reads (usage_credits, topup_credits) resolve. There are no plans or
subscriptions — the org's credit budget is the whole response. Covers the
populated path, the unprovisioned path, topup aggregation, and unlimited.
"""

from tests.helpers.supabase_mocks import mock_select

ENDPOINT = "/api/v2/billing/overview"


def test_overview_returns_org_credit_budget(recruiter_client, respx_mock):
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
    assert body["intake_total"] == 100
    assert body["intake_used"] == 20
    assert body["intake_topup"] == 15  # 10 + 5 aggregated
    assert body["interview_total"] == 50
    assert body["interview_used"] == 5
    assert body["interview_topup"] == 3


def test_overview_no_plan_or_subscription_fields(recruiter_client, respx_mock):
    """The plan/subscription concept is gone — the payload must not carry it."""
    mock_select(respx_mock, "usage_credits", [
        {"credit_type": "intake", "total": 10, "used": 0},
    ])
    mock_select(respx_mock, "topup_credits", [])

    resp = recruiter_client.get(ENDPOINT)
    assert resp.status_code == 200
    body = resp.json()
    for gone in (
        "plan_name",
        "plan_display_name",
        "subscription_status",
        "period_start",
        "period_end",
        "cancel_at_period_end",
    ):
        assert gone not in body


def test_overview_unprovisioned_org_defaults_to_zero(recruiter_client, respx_mock):
    mock_select(respx_mock, "usage_credits", [])
    mock_select(respx_mock, "topup_credits", [])

    resp = recruiter_client.get(ENDPOINT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["intake_total"] == 0
    assert body["intake_used"] == 0
    assert body["interview_total"] == 0
    assert body["interview_topup"] == 0


def test_overview_passes_through_unlimited_sentinel(recruiter_client, respx_mock):
    mock_select(respx_mock, "usage_credits", [
        {"credit_type": "interview", "total": -1, "used": 7},
    ])
    mock_select(respx_mock, "topup_credits", [])

    resp = recruiter_client.get(ENDPOINT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["interview_total"] == -1
    assert body["interview_used"] == 7


def test_overview_requires_auth(unauthed_client):
    resp = unauthed_client.get(ENDPOINT)
    assert resp.status_code in (401, 403)
