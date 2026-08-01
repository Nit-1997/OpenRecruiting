"""
Interview / intake credit accounting.

Two-tier model (per migration 41 + 38):
  - `usage_credits` — monthly bucket per (org, credit_type). `total = -1`
    means unlimited (enterprise).
  - `topup_credits` — pay-as-you-go fallback consumed only when the
    monthly bucket is exhausted.

`use_credit` calls the `use_credit_atomic` Postgres function which
handles both buckets in a single transaction (CAS-safe under concurrent
recall webhooks / scheduling).

Ported byte-for-byte from `backend/v1/app/services/credit_service.py`
to keep v1 and v2 in lockstep until a shared package is introduced. The
file is small (~80 lines) and stable; drift risk is acceptable for now.
"""

from fastapi import HTTPException

from app.logging_config import get_logger
from app.services.supabase import get_supabase_admin_client


logger = get_logger(__name__)


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
                    f"You've used all your {credit_type} credits. "
                    "Upgrade your plan to continue."
                ),
                "upgrade_url": "/dashboard/billing",
            },
        )
    logger.info(f"Credit used: org={org_id} type={credit_type} source={source}")
