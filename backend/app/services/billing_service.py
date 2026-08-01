from dodopayments import AsyncDodoPayments
from app.config import get_settings
from app.services.supabase import get_supabase_admin_client
from app.logging_config import get_logger
from app.utils import parse_iso_datetime

logger = get_logger(__name__)


class BillingServiceError(Exception):
    def __init__(self, message: str, error_code: str = None):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class BillingService:
    def __init__(self):
        settings = get_settings()
        self.dodo = AsyncDodoPayments(
            bearer_token=settings.DODO_PAYMENTS_API_KEY,
            environment=settings.DODO_ENVIRONMENT,
        )
        self.frontend_url = settings.RECRUITER_PORTAL_URL

    async def get_plan_by_name(self, plan_name: str) -> dict:
        supabase = get_supabase_admin_client()
        result = await supabase.table("plans") \
            .select("*") \
            .eq("name", plan_name) \
            .eq("is_active", True) \
            .single() \
            .execute_async()
        if not result.data:
            raise BillingServiceError(f"Plan not found: {plan_name}", "plan_not_found")
        return result.data

    async def get_active_plans(self) -> list[dict]:
        supabase = get_supabase_admin_client()
        result = await supabase.table("plans") \
            .select("*") \
            .eq("is_active", True) \
            .order("price_cents") \
            .execute_async()
        return result.data or []

    async def get_topup_products(self) -> list[dict]:
        supabase = get_supabase_admin_client()
        result = await supabase.table("topup_products") \
            .select("*") \
            .eq("is_active", True) \
            .execute_async()
        return result.data or []

    async def get_active_promotion(self) -> dict | None:
        supabase = get_supabase_admin_client()
        result = await supabase.table("promotions") \
            .select("*") \
            .eq("is_active", True) \
            .limit(1) \
            .execute_async()
        return result.data[0] if result.data else None

    async def create_subscription_checkout(
        self, org_id: str, plan_name: str, user_email: str, user_name: str, discount_code: str = None
    ) -> str:
        plan = await self.get_plan_by_name(plan_name)
        if not plan.get("dodo_product_id"):
            raise BillingServiceError("Plan has no payment product configured", "no_product")

        kwargs = {
            "product_cart": [{
                "product_id": plan["dodo_product_id"],
                "quantity": 1,
            }],
            "customer": {
                "email": user_email,
                "name": user_name,
            },
            "return_url": f"{self.frontend_url}/dashboard/billing/success?plan={plan_name}",
            "metadata": {
                "organization_id": org_id,
                "plan_name": plan_name,
                "type": "subscription",
            },
        }
        if discount_code:
            kwargs["discount_code"] = discount_code

        session = await self.dodo.checkout_sessions.create(**kwargs)
        return session.checkout_url

    async def create_topup_checkout(
        self, org_id: str, topup_product_id: str, user_email: str, user_name: str
    ) -> str:
        supabase = get_supabase_admin_client()
        result = await supabase.table("topup_products") \
            .select("*") \
            .eq("id", topup_product_id) \
            .eq("is_active", True) \
            .single() \
            .execute_async()

        if not result.data:
            raise BillingServiceError("Top-up product not found", "topup_not_found")

        product = result.data
        if not product.get("dodo_product_id"):
            raise BillingServiceError("Top-up product has no payment product configured", "no_product")

        session = await self.dodo.checkout_sessions.create(
            product_cart=[{
                "product_id": product["dodo_product_id"],
                "quantity": 1,
            }],
            customer={
                "email": user_email,
                "name": user_name,
            },
            return_url=f"{self.frontend_url}/dashboard/billing?topup=success",
            metadata={
                "organization_id": org_id,
                "topup_product_id": topup_product_id,
                "type": "topup",
            },
        )
        return session.checkout_url

    async def get_org_subscription(self, org_id: str) -> dict | None:
        supabase = get_supabase_admin_client()
        result = await supabase.table("subscriptions") \
            .select("*, plans(*)") \
            .eq("organization_id", org_id) \
            .eq("status", "active") \
            .single() \
            .execute_async()
        return result.data

    async def get_org_credits(self, org_id: str) -> list[dict]:
        supabase = get_supabase_admin_client()
        result = await supabase.table("usage_credits") \
            .select("*") \
            .eq("organization_id", org_id) \
            .execute_async()
        return result.data or []

    async def get_org_topup_balance(self, org_id: str) -> dict[str, int]:
        supabase = get_supabase_admin_client()
        result = await supabase.table("topup_credits") \
            .select("credit_type, remaining") \
            .eq("organization_id", org_id) \
            .execute_async()

        balance: dict[str, int] = {}
        for row in (result.data or []):
            if row["remaining"] > 0:
                ct = row["credit_type"]
                balance[ct] = balance.get(ct, 0) + row["remaining"]
        return balance

    async def activate_subscription(
        self, org_id: str, plan_name: str, dodo_subscription_id: str, dodo_customer_id: str
    ):
        supabase = get_supabase_admin_client()
        plan = await self.get_plan_by_name(plan_name)

        await supabase.table("subscriptions") \
            .update({"status": "cancelled", "updated_at": "now()"}) \
            .eq("organization_id", org_id) \
            .eq("status", "active") \
            .execute_async()

        await supabase.table("subscriptions").insert({
            "organization_id": org_id,
            "plan_id": plan["id"],
            "status": "active",
            "dodo_subscription_id": dodo_subscription_id,
            "dodo_customer_id": dodo_customer_id,
            "current_period_start": "now()",
        }).execute_async()

        await self._reset_monthly_credits(org_id, plan)
        logger.info(f"Subscription activated: org={org_id} plan={plan_name}")

    async def reset_credits_for_renewal(self, org_id: str):
        sub = await self.get_org_subscription(org_id)
        if not sub or not sub.get("plans"):
            return
        plan = sub["plans"]
        await self._reset_monthly_credits(org_id, plan)
        logger.info(f"Monthly credits reset for renewal: org={org_id}")

    async def update_subscription_status(self, dodo_subscription_id: str, new_status: str):
        supabase = get_supabase_admin_client()
        await supabase.table("subscriptions") \
            .update({"status": new_status, "updated_at": "now()"}) \
            .eq("dodo_subscription_id", dodo_subscription_id) \
            .execute_async()
        logger.info(f"Subscription status updated: dodo_sub={dodo_subscription_id} status={new_status}")

    async def cancel_subscription(self, org_id: str) -> dict | None:
        supabase = get_supabase_admin_client()
        result = await supabase.table("subscriptions") \
            .select("id, dodo_subscription_id, is_manual, current_period_end") \
            .eq("organization_id", org_id) \
            .eq("status", "active") \
            .single() \
            .execute_async()

        if not result.data:
            return None

        sub = result.data
        dodo_sub_id = sub.get("dodo_subscription_id")
        is_manual = sub.get("is_manual", False)

        if dodo_sub_id and not is_manual:
            try:
                await self.dodo.subscriptions.update(
                    dodo_sub_id,
                    status="cancelled",
                )
                logger.info(f"Dodo subscription cancelled: {dodo_sub_id}")
            except Exception as e:
                logger.error(f"Failed to cancel Dodo subscription {dodo_sub_id}: {e}")

        await supabase.table("subscriptions") \
            .update({"status": "cancelled", "cancel_at_period_end": True, "updated_at": "now()"}) \
            .eq("id", sub["id"]) \
            .execute_async()

        logger.info(f"Subscription cancelled: org={org_id}")
        return sub

    async def grant_topup_credits(self, org_id: str, topup_product_id: str, dodo_payment_id: str):
        supabase = get_supabase_admin_client()
        product_result = await supabase.table("topup_products") \
            .select("credit_type, credit_amount") \
            .eq("id", topup_product_id) \
            .single() \
            .execute_async()

        if not product_result.data:
            logger.warning(f"Top-up product not found: {topup_product_id}")
            return

        product = product_result.data
        await supabase.table("topup_credits").insert({
            "organization_id": org_id,
            "credit_type": product["credit_type"],
            "amount": product["credit_amount"],
            "remaining": product["credit_amount"],
            "dodo_payment_id": dodo_payment_id,
        }).execute_async()

        logger.info(f"Top-up credits granted: org={org_id} type={product['credit_type']} amount={product['credit_amount']}")

    async def validate_promo_code(self, code: str) -> dict:
        supabase = get_supabase_admin_client()
        normalized = code.strip().upper()
        result = await supabase.table("promotions") \
            .select("*") \
            .eq("code", normalized) \
            .eq("is_active", True) \
            .limit(1) \
            .execute_async()

        if not result.data:
            return {"valid": False, "message": "Invalid or expired promo code"}

        promo = result.data[0]
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        if promo.get("start_date"):
            start = parse_iso_datetime(promo["start_date"])
            if now < start:
                return {"valid": False, "message": "This promo code is not yet active"}

        if promo.get("end_date"):
            end = parse_iso_datetime(promo["end_date"])
            if now > end:
                return {"valid": False, "message": "This promo code has expired"}

        return {
            "valid": True,
            "code": promo["code"],
            "percent_off": promo["percent_off"],
            "message": f"{promo['percent_off']}% discount applied",
        }

    async def get_subscription_by_dodo_id(self, dodo_subscription_id: str) -> dict | None:
        supabase = get_supabase_admin_client()
        result = await supabase.table("subscriptions") \
            .select("organization_id") \
            .eq("dodo_subscription_id", dodo_subscription_id) \
            .single() \
            .execute_async()
        return result.data

    async def _reset_monthly_credits(self, org_id: str, plan: dict, subscription: dict = None):
        supabase = get_supabase_admin_client()
        for credit_type, total_field in [("intake", "intake_credits"), ("interview", "interview_credits")]:
            custom_key = f"custom_{total_field}"
            total = (subscription or {}).get(custom_key) if subscription and (subscription or {}).get(custom_key) is not None else plan[total_field]
            existing = await supabase.table("usage_credits") \
                .select("id") \
                .eq("organization_id", org_id) \
                .eq("credit_type", credit_type) \
                .execute_async()

            if existing.data:
                await supabase.table("usage_credits") \
                    .update({"total": total, "used": 0, "period_start": "now()"}) \
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


_billing_service = None


def get_billing_service() -> BillingService:
    global _billing_service
    if _billing_service is None:
        _billing_service = BillingService()
    return _billing_service
