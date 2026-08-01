"""Behavioral tests for BillingService — plan/credit reads, checkout creation,
subscription activation/cancellation, top-up grants, promo validation, and the
monthly-credit reset math.

The Dodo SDK client is replaced with an AsyncMock so no payment API is hit, and
Supabase IO goes through a fluent MagicMock stub keyed per-table where needed.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.billing_service as billing_mod
from app.services.billing_service import BillingService, BillingServiceError, get_billing_service


@pytest.fixture
def svc():
    """A BillingService whose Dodo client is an AsyncMock (constructor patched)."""
    with patch.object(billing_mod, "AsyncDodoPayments") as mock_dodo:
        mock_dodo.return_value = MagicMock()
        s = BillingService()
    s.dodo = MagicMock()
    s.dodo.checkout_sessions.create = AsyncMock()
    s.dodo.subscriptions.update = AsyncMock()
    return s


def _builder(execute_result):
    b = MagicMock()
    for m in ("table", "select", "insert", "update", "eq", "order", "limit", "single", "neq"):
        getattr(b, m).return_value = b
    b.execute_async = AsyncMock(return_value=execute_result)
    return b


def _supa_returning(execute_result):
    b = _builder(execute_result)
    supa = MagicMock()
    supa.table.return_value = b
    return supa, b


def _resp(data):
    return MagicMock(data=data)


# ---------------------------------------------------------------------------
# get_plan_by_name
# ---------------------------------------------------------------------------


async def test_get_plan_by_name_found(svc):
    supa, _ = _supa_returning(_resp({"id": "plan-1", "name": "Pro"}))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        plan = await svc.get_plan_by_name("Pro")
    assert plan["id"] == "plan-1"


async def test_get_plan_by_name_not_found_raises(svc):
    supa, _ = _supa_returning(_resp(None))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        with pytest.raises(BillingServiceError) as e:
            await svc.get_plan_by_name("Ghost")
    assert e.value.error_code == "plan_not_found"


async def test_get_active_plans_and_topups(svc):
    supa, _ = _supa_returning(_resp([{"id": "p1"}, {"id": "p2"}]))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        plans = await svc.get_active_plans()
        topups = await svc.get_topup_products()
    assert len(plans) == 2 and len(topups) == 2


async def test_get_active_promotion_none(svc):
    supa, _ = _supa_returning(_resp([]))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        assert await svc.get_active_promotion() is None


async def test_get_active_promotion_found(svc):
    supa, _ = _supa_returning(_resp([{"code": "SAVE10"}]))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        promo = await svc.get_active_promotion()
    assert promo["code"] == "SAVE10"


# ---------------------------------------------------------------------------
# checkout creation
# ---------------------------------------------------------------------------


async def test_create_subscription_checkout_returns_url(svc):
    supa, _ = _supa_returning(_resp({"id": "plan-1", "name": "Pro", "dodo_product_id": "prod-1"}))
    svc.dodo.checkout_sessions.create.return_value = MagicMock(checkout_url="https://pay/abc")
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        url = await svc.create_subscription_checkout(
            org_id="o1", plan_name="Pro", user_email="a@b.com", user_name="A", discount_code="SAVE10"
        )
    assert url == "https://pay/abc"
    # discount_code propagated into the create kwargs.
    kwargs = svc.dodo.checkout_sessions.create.call_args.kwargs
    assert kwargs["discount_code"] == "SAVE10"
    assert kwargs["metadata"]["organization_id"] == "o1"


async def test_create_subscription_checkout_no_product_raises(svc):
    supa, _ = _supa_returning(_resp({"id": "plan-1", "name": "Pro", "dodo_product_id": None}))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        with pytest.raises(BillingServiceError) as e:
            await svc.create_subscription_checkout(
                org_id="o1", plan_name="Pro", user_email="a@b.com", user_name="A"
            )
    assert e.value.error_code == "no_product"


async def test_create_topup_checkout_returns_url(svc):
    supa, _ = _supa_returning(_resp({"id": "tp-1", "dodo_product_id": "prod-2"}))
    svc.dodo.checkout_sessions.create.return_value = MagicMock(checkout_url="https://pay/topup")
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        url = await svc.create_topup_checkout(
            org_id="o1", topup_product_id="tp-1", user_email="a@b.com", user_name="A"
        )
    assert url == "https://pay/topup"


async def test_create_topup_checkout_not_found_raises(svc):
    supa, _ = _supa_returning(_resp(None))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        with pytest.raises(BillingServiceError) as e:
            await svc.create_topup_checkout(
                org_id="o1", topup_product_id="ghost", user_email="a@b.com", user_name="A"
            )
    assert e.value.error_code == "topup_not_found"


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


async def test_get_org_subscription(svc):
    supa, _ = _supa_returning(_resp({"id": "sub-1", "plans": {"name": "Pro"}}))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        sub = await svc.get_org_subscription("o1")
    assert sub["id"] == "sub-1"


async def test_get_org_credits_empty(svc):
    supa, _ = _supa_returning(_resp(None))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        assert await svc.get_org_credits("o1") == []


async def test_get_org_topup_balance_sums_positive_only(svc):
    rows = [
        {"credit_type": "interview", "remaining": 3},
        {"credit_type": "interview", "remaining": 2},
        {"credit_type": "intake", "remaining": 0},  # skipped (not > 0)
        {"credit_type": "intake", "remaining": 5},
    ]
    supa, _ = _supa_returning(_resp(rows))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        balance = await svc.get_org_topup_balance("o1")
    assert balance == {"interview": 5, "intake": 5}


async def test_get_subscription_by_dodo_id(svc):
    supa, _ = _supa_returning(_resp({"organization_id": "o1"}))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        sub = await svc.get_subscription_by_dodo_id("dodo-1")
    assert sub["organization_id"] == "o1"


# ---------------------------------------------------------------------------
# activate / reset / cancel
# ---------------------------------------------------------------------------


async def test_activate_subscription_resets_credits(svc):
    """activate_subscription cancels prior active sub, inserts new, then resets
    monthly credits. We stub get_plan_by_name + the credit-reset existing-check."""
    plan = {"id": "plan-1", "name": "Pro", "intake_credits": 10, "interview_credits": 20}
    supa, builder = _supa_returning(_resp([]))  # generic empty -> insert paths
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa), \
         patch.object(svc, "get_plan_by_name", AsyncMock(return_value=plan)):
        await svc.activate_subscription("o1", "Pro", "dodo-sub-1", "dodo-cust-1")
    # subscriptions update (cancel) + insert both ran.
    assert builder.update.called and builder.insert.called


async def test_reset_credits_for_renewal_noop_without_sub(svc):
    with patch.object(svc, "get_org_subscription", AsyncMock(return_value=None)):
        # Should return quietly without touching the DB.
        await svc.reset_credits_for_renewal("o1")


async def test_reset_credits_for_renewal_runs_with_plan(svc):
    sub = {"plans": {"intake_credits": 5, "interview_credits": 7}}
    supa, builder = _supa_returning(_resp([{"id": "uc-1"}]))  # existing usage_credits -> update
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa), \
         patch.object(svc, "get_org_subscription", AsyncMock(return_value=sub)):
        await svc.reset_credits_for_renewal("o1")
    assert builder.update.called


async def test_update_subscription_status(svc):
    supa, builder = _supa_returning(_resp([]))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        await svc.update_subscription_status("dodo-1", "cancelled")
    builder.update.assert_called()


async def test_cancel_subscription_none_when_no_active(svc):
    supa, _ = _supa_returning(_resp(None))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        assert await svc.cancel_subscription("o1") is None


async def test_cancel_subscription_cancels_dodo_and_db(svc):
    sub = {"id": "sub-1", "dodo_subscription_id": "dodo-1", "is_manual": False}
    supa, builder = _supa_returning(_resp(sub))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        result = await svc.cancel_subscription("o1")
    assert result["id"] == "sub-1"
    svc.dodo.subscriptions.update.assert_awaited_once()
    builder.update.assert_called()


async def test_cancel_subscription_manual_skips_dodo(svc):
    sub = {"id": "sub-1", "dodo_subscription_id": "dodo-1", "is_manual": True}
    supa, _ = _supa_returning(_resp(sub))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        await svc.cancel_subscription("o1")
    svc.dodo.subscriptions.update.assert_not_called()


async def test_cancel_subscription_swallows_dodo_error(svc):
    sub = {"id": "sub-1", "dodo_subscription_id": "dodo-1", "is_manual": False}
    supa, builder = _supa_returning(_resp(sub))
    svc.dodo.subscriptions.update.side_effect = RuntimeError("dodo down")
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        # Dodo failure must NOT prevent the DB cancel.
        result = await svc.cancel_subscription("o1")
    assert result["id"] == "sub-1"
    builder.update.assert_called()


# ---------------------------------------------------------------------------
# top-up grants
# ---------------------------------------------------------------------------


async def test_grant_topup_credits_inserts(svc):
    supa, builder = _supa_returning(_resp({"credit_type": "interview", "credit_amount": 10}))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        await svc.grant_topup_credits("o1", "tp-1", "pay-1")
    builder.insert.assert_called()


async def test_grant_topup_credits_missing_product_noop(svc):
    supa, builder = _supa_returning(_resp(None))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        await svc.grant_topup_credits("o1", "ghost", "pay-1")
    builder.insert.assert_not_called()


# ---------------------------------------------------------------------------
# promo validation
# ---------------------------------------------------------------------------


async def test_validate_promo_code_invalid(svc):
    supa, _ = _supa_returning(_resp([]))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        result = await svc.validate_promo_code("nope")
    assert result["valid"] is False


async def test_validate_promo_code_not_yet_active(svc):
    future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    supa, _ = _supa_returning(_resp([{"code": "EARLY", "percent_off": 10, "start_date": future}]))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        result = await svc.validate_promo_code("early")
    assert result["valid"] is False and "not yet active" in result["message"]


async def test_validate_promo_code_expired(svc):
    past = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    supa, _ = _supa_returning(_resp([{"code": "OLD", "percent_off": 10, "end_date": past}]))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        result = await svc.validate_promo_code("old")
    assert result["valid"] is False and "expired" in result["message"]


async def test_validate_promo_code_valid(svc):
    supa, _ = _supa_returning(_resp([{"code": "SAVE20", "percent_off": 20}]))
    with patch.object(billing_mod, "get_supabase_admin_client", return_value=supa):
        result = await svc.validate_promo_code(" save20 ")
    assert result["valid"] is True
    assert result["percent_off"] == 20
    assert result["code"] == "SAVE20"


# ---------------------------------------------------------------------------
# singleton
# ---------------------------------------------------------------------------


def test_get_billing_service_is_cached():
    with patch.object(billing_mod, "AsyncDodoPayments", return_value=MagicMock()):
        billing_mod._billing_service = None
        try:
            a = get_billing_service()
            b = get_billing_service()
            assert a is b
        finally:
            billing_mod._billing_service = None
