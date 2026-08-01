"""Reconcile fallback (spec 2026-06-14 §5 trigger 2): periodically pull interviews
for every active connection's candidate applications and idempotently upsert them.
Catches whatever the Knit webhook missed (silent sync, interview-only changes that
don't modify the application). Convergence with the webhook path is guaranteed by
the ats_upsert_interview key — running both never double-ingests.

Lifespan task, gated by RUN_BACKGROUND_WORKERS AND ATS_INTEGRATIONS_ENABLED.
Per-application and per-connection isolation mirrors ats_sync/drainer."""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.integrations.ats.core.registry import get_ats_provider
from app.logging_config import get_logger
from app.services.ats_sync.interview_actions import act_on_promoted_interviews
from app.services.ats_sync.interview_pull import pull_interviews_for_application

logger = get_logger(__name__)


async def _active_connections(supabase) -> list[dict]:
    res = await (
        supabase.table("ats_connections")
        .select("id, organization_id, provider, knit_integration_id")
        .eq("status", "active")
        .execute_async()
    )
    return res.data or []


async def _application_ids(
    supabase, org_id: str, provider: str, limit: int
) -> list[str]:
    # Scope to THIS connection's provider — otherwise an org with another provider's
    # links (e.g. 111 inactive-Workable apps) crowds out / starves the active
    # provider's apps within the batch cap, and we'd pointlessly call the active
    # adapter for foreign applications. (Caught live: Ashby interview apps were
    # dropped because Workable links filled the first 100.)
    res = await (
        supabase.table("ats_entity_links")
        .select("ats_id")
        .eq("organization_id", org_id)
        .eq("provider", provider)
        .eq("ats_type", "application")
        .eq("ats_deleted", False)
        .limit(limit)
        .execute_async()
    )
    return [r["ats_id"] for r in (res.data or []) if r.get("ats_id")]


async def _promote_planned_req(
    *,
    supabase,
    requisition_id,
    organization_id,
    bundle=None,
    _promoted_override=None,
) -> None:
    """Promote a single planned req's staged interviews and act on the result
    (Phase C: Recall / transcript / feedback). Best-effort — a failure for one
    req never aborts the sweep. `_promoted_override` is a unit-test seam; the
    real path runs ats_promote_interviews via call_rpc."""
    try:
        if _promoted_override is not None:
            promoted = _promoted_override
        else:
            from app.api.v2.core.rpc import call_rpc

            promoted = await call_rpc(
                supabase,
                "ats_promote_interviews",
                {
                    "p_requisition_id": str(requisition_id),
                    "p_org": str(organization_id),
                },
            ) or []
        await act_on_promoted_interviews(supabase, promoted, bundle=bundle)
    except Exception as exc:  # noqa: BLE001 — isolate per requisition
        logger.warning(
            "ats_reconcile_promotion_failed",
            extra={
                "event": "ats_reconcile_promotion_failed",
                "requisition_id": str(requisition_id),
                "error": str(exc),
            },
        )


async def _planned_reqs_with_unpromoted_interviews(
    supabase, org_id: str
) -> list[str]:
    """Cheap discovery: requisitions of this org in status 'planned' that still
    have staged ats_interviews (candidate_round_id IS NULL). Links interviews to
    a req via ats_stage_round_map (ats_interviews has no requisition_id). Returns
    [] fast when nothing is un-promoted."""
    staged = await (
        supabase.table("ats_interviews")
        .select("ats_stage_id")
        .eq("organization_id", org_id)
        .is_null("candidate_round_id")
        .execute_async()
    )
    stage_ids = sorted(
        {
            r["ats_stage_id"]
            for r in (staged.data or [])
            if r.get("ats_stage_id")
        }
    )
    if not stage_ids:
        return []

    mapped = await (
        supabase.table("ats_stage_round_map")
        .select("requisition_id")
        .eq("organization_id", org_id)
        .in_("ats_stage_id", stage_ids)
        .execute_async()
    )
    req_ids = sorted(
        {
            r["requisition_id"]
            for r in (mapped.data or [])
            if r.get("requisition_id")
        }
    )
    if not req_ids:
        return []

    planned = await (
        supabase.table("requisitions")
        .select("id")
        .in_("id", req_ids)
        .eq("status", "planned")
        .execute_async()
    )
    return [r["id"] for r in (planned.data or []) if r.get("id")]


async def _promote_un_promoted_interviews(supabase, org_id: str, *, bundle) -> None:
    """For every planned req of the org with un-promoted interviews, promote +
    act. Closes the loop for interviews that arrive AFTER publish (the publish
    hook only promotes the req it published). Best-effort per req."""
    try:
        req_ids = await _planned_reqs_with_unpromoted_interviews(supabase, org_id)
    except Exception as exc:  # noqa: BLE001 — discovery failure never kills sweep
        logger.warning(
            "ats_reconcile_promote_discovery_failed",
            extra={
                "event": "ats_reconcile_promote_discovery_failed",
                "organization_id": org_id,
                "error": str(exc),
            },
        )
        return
    for requisition_id in req_ids:
        await _promote_planned_req(
            supabase=supabase,
            requisition_id=requisition_id,
            organization_id=org_id,
            bundle=bundle,
        )


async def reconcile_interviews_once(supabase) -> int:
    """One reconcile tick across all active connections. Returns total events upserted."""
    settings = get_settings()
    batch = settings.ATS_INTERVIEW_RECONCILE_BATCH
    total = 0
    for conn in await _active_connections(supabase):
        org_id = conn["organization_id"]
        try:
            bundle = await get_ats_provider(supabase, org_id)
        except Exception as exc:  # noqa: BLE001 — one bad connection never kills the sweep
            logger.warning(
                "ats_reconcile_bundle_failed",
                extra={"organization_id": org_id, "error": str(exc)},
            )
            continue
        if getattr(bundle, "interviews", None) is None:
            continue  # provider has no native interviews — nothing to reconcile
        for application_id in await _application_ids(
            supabase, org_id, conn["provider"], batch
        ):
            try:
                total += await pull_interviews_for_application(
                    supabase, bundle, org_id, application_id
                )
            except Exception as exc:  # noqa: BLE001 — isolate per application
                logger.warning(
                    "ats_reconcile_application_failed",
                    extra={
                        "organization_id": org_id,
                        "application_id": application_id,
                        "error": str(exc),
                    },
                )
        # Phase C: after the per-application upserts, promote interviews that
        # arrived AFTER publish (planned reqs with un-promoted staged rows) and
        # act on them (Recall / transcript / feedback). Reuses this connection's
        # bundle. Best-effort — never affects the upsert count or the sweep.
        await _promote_un_promoted_interviews(supabase, org_id, bundle=bundle)
    return total


async def run_ats_interview_reconcile(supabase) -> None:
    """Forever-loop; cancelled on app shutdown via the lifespan context."""
    interval = get_settings().ATS_INTERVIEW_RECONCILE_INTERVAL_S
    logger.info("ats_interview_reconcile_started", extra={"interval_s": interval})
    while True:
        try:
            total = await reconcile_interviews_once(supabase)
            if total:
                logger.info(
                    "ats_interview_reconcile_upserted",
                    extra={"event": "ats_interview_reconcile_upserted", "n": total},
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ats_interview_reconcile_error", extra={"error": str(exc)}
            )
        await asyncio.sleep(interval)
