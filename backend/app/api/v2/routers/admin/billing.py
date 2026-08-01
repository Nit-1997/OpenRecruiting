from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.dependencies import require_staff, CurrentUser, invalidate_profile_cache
from app.services.supabase import get_supabase_admin_client
from app.services.billing_service import get_billing_service

from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/billing", tags=["Admin - Billing"])


class ManualSubscriptionCreate(BaseModel):
    organization_id: UUID
    plan_name: str = "enterprise"
    custom_price_dollars: Optional[float] = None
    custom_intake_credits: Optional[int] = None
    custom_interview_credits: Optional[int] = None
    custom_max_users: Optional[int] = None
    current_period_end: Optional[datetime] = None


class ManualSubscriptionUpdate(BaseModel):
    plan_name: Optional[str] = None
    custom_price_dollars: Optional[float] = None
    custom_intake_credits: Optional[int] = None
    custom_interview_credits: Optional[int] = None
    custom_max_users: Optional[int] = None
    current_period_end: Optional[datetime] = None
    status: Optional[str] = None


class MigrateUserRequest(BaseModel):
    user_id: UUID
    cancel_existing_subscription: bool = True


class SubscriptionAdminResponse(BaseModel):
    id: UUID
    organization_id: UUID
    org_name: Optional[str] = None
    plan_id: UUID
    plan_name: Optional[str] = None
    plan_display_name: Optional[str] = None
    status: str
    is_manual: bool = False
    custom_price_cents: Optional[int] = None
    custom_intake_credits: Optional[int] = None
    custom_interview_credits: Optional[int] = None
    custom_max_users: Optional[int] = None
    dodo_subscription_id: Optional[str] = None
    current_period_start: Optional[str] = None
    current_period_end: Optional[str] = None
    cancel_at_period_end: bool = False

    model_config = {"from_attributes": True, "extra": "ignore"}


@router.get("/subscriptions", response_model=list[SubscriptionAdminResponse])
async def list_subscriptions(
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    result = await supabase.table("subscriptions") \
        .select("*, plans(name, display_name), organizations(name)") \
        .order("created_at", desc=True) \
        .execute_async()

    subs = []
    for row in (result.data or []):
        plan_data = row.pop("plans", {}) or {}
        org_data = row.pop("organizations", {}) or {}
        subs.append(SubscriptionAdminResponse(
            **row,
            plan_name=plan_data.get("name"),
            plan_display_name=plan_data.get("display_name"),
            org_name=org_data.get("name"),
        ))
    return subs


async def _sync_usage_credits(supabase, org_id: str, plan: dict, custom_intake: int | None, custom_interview: int | None, reset_used: bool = True):
    intake_total = custom_intake if custom_intake is not None else plan["intake_credits"]
    interview_total = custom_interview if custom_interview is not None else plan["interview_credits"]

    for credit_type, total in [("intake", intake_total), ("interview", interview_total)]:
        existing = await supabase.table("usage_credits") \
            .select("id") \
            .eq("organization_id", org_id) \
            .eq("credit_type", credit_type) \
            .execute_async()

        if existing.data:
            update_payload: dict = {"total": total}
            if reset_used:
                update_payload["used"] = 0
                update_payload["period_start"] = "now()"
            await supabase.table("usage_credits") \
                .update(update_payload) \
                .eq("organization_id", org_id) \
                .eq("credit_type", credit_type) \
                .execute_async()
        else:
            await supabase.table("usage_credits").insert({
                "organization_id": org_id,
                "credit_type": credit_type,
                "total": total,
                "used": 0,
                "period_start": "now()",
            }).execute_async()


async def _sync_org_type(supabase, org_id: str, plan_name: str):
    if plan_name == "enterprise":
        await supabase.table("organizations") \
            .update({"org_type": "enterprise"}) \
            .eq("id", org_id) \
            .execute_async()


@router.post("/subscriptions", response_model=SubscriptionAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_manual_subscription(
    req: ManualSubscriptionCreate,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    service = get_billing_service()

    plan = await service.get_plan_by_name(req.plan_name)

    await supabase.table("subscriptions") \
        .update({"status": "cancelled", "updated_at": "now()"}) \
        .eq("organization_id", str(req.organization_id)) \
        .eq("status", "active") \
        .execute_async()

    sub_data = {
        "organization_id": str(req.organization_id),
        "plan_id": plan["id"],
        "status": "active",
        "is_manual": True,
        "current_period_start": "now()",
    }
    if req.custom_price_dollars is not None:
        sub_data["custom_price_cents"] = int(req.custom_price_dollars * 100)
    if req.custom_intake_credits is not None:
        sub_data["custom_intake_credits"] = req.custom_intake_credits
    if req.custom_interview_credits is not None:
        sub_data["custom_interview_credits"] = req.custom_interview_credits
    if req.custom_max_users is not None:
        sub_data["custom_max_users"] = req.custom_max_users
    if req.current_period_end is not None:
        sub_data["current_period_end"] = req.current_period_end.isoformat()

    result = await supabase.table("subscriptions") \
        .insert(sub_data) \
        .execute_async()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create subscription")

    await _sync_org_type(supabase, str(req.organization_id), req.plan_name)
    await _sync_usage_credits(supabase, str(req.organization_id), plan, req.custom_intake_credits, req.custom_interview_credits)

    row = result.data[0] if isinstance(result.data, list) else result.data
    return SubscriptionAdminResponse(
        **row,
        plan_name=req.plan_name,
        plan_display_name=plan["display_name"],
    )


@router.put("/subscriptions/{sub_id}", response_model=SubscriptionAdminResponse)
async def update_manual_subscription(
    sub_id: UUID,
    req: ManualSubscriptionUpdate,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    update_data = {}

    if req.plan_name:
        service = get_billing_service()
        plan = await service.get_plan_by_name(req.plan_name)
        update_data["plan_id"] = plan["id"]

    if req.custom_price_dollars is not None:
        update_data["custom_price_cents"] = int(req.custom_price_dollars * 100)
    if req.custom_intake_credits is not None:
        update_data["custom_intake_credits"] = req.custom_intake_credits
    if req.custom_interview_credits is not None:
        update_data["custom_interview_credits"] = req.custom_interview_credits
    if req.custom_max_users is not None:
        update_data["custom_max_users"] = req.custom_max_users
    if req.current_period_end is not None:
        update_data["current_period_end"] = req.current_period_end.isoformat()
    if req.status:
        update_data["status"] = req.status

    update_data["updated_at"] = "now()"

    await supabase.table("subscriptions") \
        .update(update_data) \
        .eq("id", str(sub_id)) \
        .execute_async()

    result = await supabase.table("subscriptions") \
        .select("*, plans(name, display_name), organizations(name)") \
        .eq("id", str(sub_id)) \
        .execute_async()

    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")

    row = result.data[0] if isinstance(result.data, list) else result.data
    plan_data = row.pop("plans", {}) or {}
    org_data = row.pop("organizations", {}) or {}
    org_id = str(row.get("organization_id", ""))

    credits_changed = req.custom_intake_credits is not None or req.custom_interview_credits is not None or req.plan_name
    if credits_changed and org_id:
        service = get_billing_service()
        resolved_plan = await service.get_plan_by_name(plan_data.get("name") or req.plan_name or "free")
        await _sync_usage_credits(
            supabase, org_id, resolved_plan,
            req.custom_intake_credits if req.custom_intake_credits is not None else row.get("custom_intake_credits"),
            req.custom_interview_credits if req.custom_interview_credits is not None else row.get("custom_interview_credits"),
            reset_used=False,
        )

    if req.plan_name and org_id:
        await _sync_org_type(supabase, org_id, req.plan_name)

    return SubscriptionAdminResponse(
        **row,
        plan_name=plan_data.get("name"),
        plan_display_name=plan_data.get("display_name"),
        org_name=org_data.get("name"),
    )


@router.delete("/subscriptions/{sub_id}")
async def delete_subscription(
    sub_id: UUID,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    await supabase.table("subscriptions") \
        .update({"status": "cancelled", "updated_at": "now()"}) \
        .eq("id", str(sub_id)) \
        .execute_async()
    return {"message": "Subscription cancelled", "id": str(sub_id)}


@router.get("/organizations/{org_id}/credits")
async def get_organization_credits(
    org_id: UUID,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()

    usage = await supabase.table("usage_credits") \
        .select("credit_type, total, used, period_start") \
        .eq("organization_id", str(org_id)) \
        .execute_async()

    topups = await supabase.table("topup_credits") \
        .select("credit_type, remaining") \
        .eq("organization_id", str(org_id)) \
        .execute_async()

    topup_map: dict[str, int] = {}
    for t in (topups.data or []):
        r = t.get("remaining", 0)
        if r > 0:
            topup_map[t["credit_type"]] = topup_map.get(t["credit_type"], 0) + r

    credits = []
    for row in (usage.data or []):
        ct = row["credit_type"]
        total = row["total"]
        used = row["used"]
        topup_remaining = topup_map.get(ct, 0)
        monthly_remaining = "unlimited" if total == -1 else max(total - used, 0)
        credits.append({
            "credit_type": ct,
            "total": total,
            "used": used,
            "monthly_remaining": monthly_remaining,
            "topup_remaining": topup_remaining,
            "effective_remaining": "unlimited" if total == -1 else max((total - used) + topup_remaining, 0),
            "period_start": row.get("period_start"),
        })

    return {"organization_id": str(org_id), "credits": credits}


@router.post("/organizations/{org_id}/migrate-user")
async def migrate_user_to_org(
    org_id: UUID,
    req: MigrateUserRequest,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()

    org_result = await supabase.table("organizations") \
        .select("id, org_type, name") \
        .eq("id", str(org_id)) \
        .is_("deleted_at", "null") \
        .single() \
        .execute_async()
    if not org_result.data:
        raise HTTPException(404, "Target organization not found")
    if org_result.data.get("org_type") != "enterprise":
        raise HTTPException(400, "Target organization must be enterprise type")

    profile_result = await supabase.table("profiles") \
        .select("id, email, organization_id") \
        .eq("id", str(req.user_id)) \
        .is_("deleted_at", "null") \
        .single() \
        .execute_async()
    if not profile_result.data:
        raise HTTPException(404, "User not found")

    user_profile = profile_result.data
    source_org_id = user_profile["organization_id"]

    if source_org_id == str(org_id):
        raise HTTPException(409, "User is already in this organization")

    sub_result = await supabase.table("subscriptions") \
        .select("custom_max_users, plan_id, plans(max_users)") \
        .eq("organization_id", str(org_id)) \
        .eq("status", "active") \
        .limit(1) \
        .execute_async()

    if sub_result.data:
        sub = sub_result.data[0] if isinstance(sub_result.data, list) else sub_result.data
        max_users = sub.get("custom_max_users")
        if max_users is None and sub.get("plans"):
            max_users = sub["plans"].get("max_users")

        if max_users and max_users != -1:
            member_count = await supabase.table("profiles") \
                .select("id") \
                .eq("organization_id", str(org_id)) \
                .is_("deleted_at", "null") \
                .count_async()
            if member_count >= max_users:
                raise HTTPException(403, f"Organization has reached maximum seats ({max_users})")

    if req.cancel_existing_subscription:
        service = get_billing_service()
        await service.cancel_subscription(source_org_id)

    await supabase.table("requisitions") \
        .update({"organization_id": str(org_id)}) \
        .eq("organization_id", source_org_id) \
        .eq("created_by", str(req.user_id)) \
        .execute_async()

    await supabase.table("profiles") \
        .update({"organization_id": str(org_id)}) \
        .eq("id", str(req.user_id)) \
        .execute_async()

    invalidate_profile_cache(str(req.user_id))

    remaining_members = await supabase.table("profiles") \
        .select("id") \
        .eq("organization_id", source_org_id) \
        .is_("deleted_at", "null") \
        .count_async()

    if remaining_members == 0:
        from datetime import datetime, timezone
        await supabase.table("organizations") \
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", source_org_id) \
            .execute_async()

    return {
        "message": "User migrated successfully",
        "user_id": str(req.user_id),
        "source_org_id": source_org_id,
        "target_org_id": str(org_id),
    }
