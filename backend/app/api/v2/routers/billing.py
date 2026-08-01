"""
Billing routes for v2.

Mounted under /api/v2/billing:
  GET  /overview   Plan info, subscription status, credit usage
"""

from fastapi import APIRouter, Depends

from app.api.v2.core.dependencies import CurrentUserWithOrg, get_current_user_with_org
from app.api.v2.schemas.billing import BillingOverview
from app.services.supabase import get_supabase_admin_client

router = APIRouter(prefix="/billing", tags=["v2/billing"])


@router.get("/overview", response_model=BillingOverview)
async def get_billing_overview(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> BillingOverview:
    supabase = get_supabase_admin_client()
    org_id = current.organization_id_str

    sub_result = await supabase.table("subscriptions") \
        .select("status, current_period_start, current_period_end, cancel_at_period_end, plans(name, display_name)") \
        .eq("organization_id", org_id) \
        .eq("status", "active") \
        .limit(1) \
        .execute_async()

    sub = sub_result.data[0] if sub_result.data else None
    plan = (sub.get("plans") or {}) if sub else {}

    credits_result = await supabase.table("usage_credits") \
        .select("credit_type, total, used") \
        .eq("organization_id", org_id) \
        .execute_async()

    credits = {r["credit_type"]: r for r in (credits_result.data or [])}

    topup_result = await supabase.table("topup_credits") \
        .select("credit_type, remaining") \
        .eq("organization_id", org_id) \
        .gt("remaining", 0) \
        .execute_async()

    topup: dict[str, int] = {}
    for r in (topup_result.data or []):
        ct = r["credit_type"]
        topup[ct] = topup.get(ct, 0) + r["remaining"]

    intake = credits.get("intake", {})
    interview = credits.get("interview", {})

    return BillingOverview(
        plan_name=plan.get("name") or "Custom",
        plan_display_name=plan.get("display_name") or plan.get("name") or "Custom",
        subscription_status=sub["status"] if sub else "none",
        period_start=sub.get("current_period_start") if sub else None,
        period_end=sub.get("current_period_end") if sub else None,
        cancel_at_period_end=bool(sub.get("cancel_at_period_end")) if sub else False,
        intake_total=intake.get("total", 0),
        intake_used=intake.get("used", 0),
        intake_topup=topup.get("intake", 0),
        interview_total=interview.get("total", 0),
        interview_used=interview.get("used", 0),
        interview_topup=topup.get("interview", 0),
    )
