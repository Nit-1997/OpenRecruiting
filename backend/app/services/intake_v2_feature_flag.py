"""Per-org feature flag lookup for v2 intake."""
from __future__ import annotations

from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)


async def is_intake_v2_enabled(supabase_client, org_id: UUID) -> bool:
    """Return True iff organizations.intake_v2_features.intake_v2_enabled is true.

    Defaults to False on any error or missing data — we never silently opt an
    org into v2.
    """
    try:
        resp = await (
            supabase_client.table("organizations")
            .select("intake_v2_features")
            .eq("id", str(org_id))
            .single()
            .execute_async()
        )
    except Exception as e:
        logger.warning("intake_v2_flag_fetch_failed", org_id=str(org_id), error=str(e))
        return False

    if not resp.data:
        return False
    features = resp.data.get("intake_v2_features") or {}
    return bool(features.get("intake_v2_enabled", False))
