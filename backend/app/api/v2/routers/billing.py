"""
Billing routes for v2.

Mounted under /api/v2/billing:
  GET  /overview   The org's credit budget and usage

There are no plans or subscriptions: the organization holds one credit
budget that all its members share. Admins set the cap from the admin portal.
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
        intake_total=intake.get("total", 0),
        intake_used=intake.get("used", 0),
        intake_topup=topup.get("intake", 0),
        interview_total=interview.get("total", 0),
        interview_used=interview.get("used", 0),
        interview_topup=topup.get("interview", 0),
    )
