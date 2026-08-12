"""
Interview / intake credit accounting.

The organization is the budget holder. Every org has a row in
`usage_credits` per credit type ('intake', 'interview') holding a `total`
cap and a running `used` count; all members of the org draw from that one
pool. There are no plan tiers — a new org is provisioned with
`DEFAULT_INTAKE_CREDITS` / `DEFAULT_INTERVIEW_CREDITS` and an admin raises
the cap from the admin portal. `total = -1` means unlimited.

`topup_credits` remains as a pay-as-you-go fallback consumed only when the
monthly bucket is exhausted. Nothing sells top-ups in an open-source
deployment, so in practice that table stays empty; the RPC still honours
it if an operator inserts rows by hand.

`use_credit` calls the `use_credit_atomic` Postgres function which handles
both buckets in a single transaction (CAS-safe under concurrent recall
webhooks / scheduling).
"""

from fastapi import HTTPException

from app.config import get_settings
from app.logging_config import get_logger
from app.services.supabase import get_supabase_admin_client


logger = get_logger(__name__)

CREDIT_TYPES = ("intake", "interview")


async def provision_default_credits(org_id: str) -> None:
    """Give a brand-new organization its starting credit budget.

    Called from both org-creation paths — admin `create_organization` and
    self-serve `signup_service`. Idempotent: a (org, credit_type) row that
    already exists is left untouched, so re-running never resets a budget
    an admin has already tuned.

    Best-effort by design. A failure here must not fail org creation — the
    org is still usable, and `use_credit_atomic` falls back to granting one
    free credit when it finds no row.
    """
    settings = get_settings()
    totals = {
        "intake": settings.DEFAULT_INTAKE_CREDITS,
        "interview": settings.DEFAULT_INTERVIEW_CREDITS,
    }
    supabase = get_supabase_admin_client()

    for credit_type in CREDIT_TYPES:
        try:
            existing = await supabase.table("usage_credits")\
                .select("id")\
                .eq("organization_id", org_id)\
                .eq("credit_type", credit_type)\
                .execute_async()
            if existing.data:
                continue

            await supabase.table("usage_credits").insert({
                "organization_id": org_id,
                "credit_type": credit_type,
                "total": totals[credit_type],
                "used": 0,
                "period_start": "now()",
            }).execute_async()
        except Exception as e:
            logger.warning(
                f"Credit provisioning failed: org={org_id} type={credit_type} err={e}"
            )

    logger.info(
        f"Credits provisioned: org={org_id} "
        f"intake={totals['intake']} interview={totals['interview']}"
    )


async def set_org_budget(
    org_id: str,
    intake_total: int | None = None,
    interview_total: int | None = None,
) -> None:
    """Set an org's credit caps. Upserts so an org that predates
    provisioning (or lost a row) gets one rather than silently no-op'ing.

    `used` is deliberately preserved — raising a cap must not erase the
    consumption history the admin is looking at when they raise it.
    """
    supabase = get_supabase_admin_client()
    totals = {"intake": intake_total, "interview": interview_total}

    for credit_type, total in totals.items():
        if total is None:
            continue

        existing = await supabase.table("usage_credits")\
            .select("id")\
            .eq("organization_id", org_id)\
            .eq("credit_type", credit_type)\
            .execute_async()

        if existing.data:
            await supabase.table("usage_credits")\
                .update({"total": total})\
                .eq("organization_id", org_id)\
                .eq("credit_type", credit_type)\
                .execute_async()
        else:
            await supabase.table("usage_credits").insert({
                "organization_id": org_id,
                "credit_type": credit_type,
                "total": total,
                "used": 0,
                "period_start": "now()",
            }).execute_async()

        logger.info(f"Credit budget set: org={org_id} type={credit_type} total={total}")


async def check_credits(org_id: str, credit_type: str) -> dict:
    """Read remaining credits without consuming any. Returns:
      {has_credits, monthly_remaining, topup_remaining, source}

    `source` is one of 'monthly', 'topup', 'none', 'free_default'.
    'free_default' fires when no `usage_credits` row exists for the org
    yet (new signup) — we hand out one free credit so the first
    interview always succeeds.
    """
    supabase = get_supabase_admin_client()

    monthly_result = await supabase.table("usage_credits")\
        .select("total, used")\
        .eq("organization_id", org_id)\
        .eq("credit_type", credit_type)\
        .single()\
        .execute_async()

    if not monthly_result.data:
        return {
            "has_credits": True,
            "monthly_remaining": 1,
            "topup_remaining": 0,
            "source": "free_default",
        }

    total = monthly_result.data["total"]
    used = monthly_result.data["used"]

    # `total = -1` is the enterprise sentinel for unlimited.
    if total == -1:
        return {
            "has_credits": True,
            "monthly_remaining": -1,
            "topup_remaining": 0,
            "source": "monthly",
        }

    monthly_remaining = max(0, total - used)
    if monthly_remaining > 0:
        return {
            "has_credits": True,
            "monthly_remaining": monthly_remaining,
            "topup_remaining": 0,
            "source": "monthly",
        }

    # Monthly exhausted — sum positive topups.
    topup_result = await supabase.table("topup_credits")\
        .select("remaining")\
        .eq("organization_id", org_id)\
        .eq("credit_type", credit_type)\
        .execute_async()

    topup_remaining = sum(
        r["remaining"] for r in (topup_result.data or []) if (r.get("remaining") or 0) > 0
    )

    return {
        "has_credits": topup_remaining > 0,
        "monthly_remaining": 0,
        "topup_remaining": topup_remaining,
        "source": "topup" if topup_remaining > 0 else "none",
    }


async def use_credit(org_id: str, credit_type: str) -> None:
    """Consume one credit. Atomic via the `use_credit_atomic` RPC
    (migration 41) which walks monthly → topups → exhausted in one tx.

    Raises HTTPException(402) on `exhausted` so callers in the request
    path can let it bubble up. The not-admitted / billing UI surfaces
    the `credits_exhausted` detail.

    Called from the webhook handler (in `bot_status_handler._charge_interview_credit`)
    — it lazy-imports this module and tolerates `ImportError`, so this
    file existing is what flips v2 from "no charge" to "real charge".
    """
    supabase = get_supabase_admin_client()
    result = await supabase.rpc("use_credit_atomic", {
        "p_org_id": org_id,
        "p_credit_type": credit_type,
    })

    source = result.data
    if source == "exhausted":
        raise HTTPException(
            status_code=402,
            detail={
                "error": "credits_exhausted",
                "credit_type": credit_type,
                "message": (
                    f"Your organization has used all of its {credit_type} "
                    "credits. Ask an administrator to raise the budget."
                ),
            },
        )
    logger.info(f"Credit used: org={org_id} type={credit_type} source={source}")
