"""Plan-seeding from Ashby interview stages (spec §8).

Pure mapping + a thin fetch helper. Filters Ashby interview stages to the
interview-bearing ones (type == 'Active') and returns seed rounds carrying
their ats_stage_id so publish can persist the ats_stage_round_map.

Native passthrough only — never unified. Best-effort: any failure to fetch
stages degrades to no seeding (the intake/publish path is unchanged for
non-ATS requisitions and resilient for ATS ones)."""

from __future__ import annotations

from typing import Any

import structlog

from app.integrations.ats.core.errors import AtsNotConnectedError
from app.integrations.ats.core.models import AtsInterviewStage
from app.integrations.ats.core.registry import get_ats_provider

logger = structlog.get_logger(__name__)

# Ashby stage `type` values that carry real interview rounds. Lead/
# PreInterviewScreen are pre-interview funnel; Offer/Hired/Archived are terminal.
# Only 'Active' stages map to OpenRecruiting plan rounds (live-confirmed: the four
# interview-bearing sandbox stages are all type 'Active').
_INTERVIEW_STAGE_TYPES = {"Active"}


def _stage_view(s: Any) -> dict[str, Any] | None:
    """Normalize a stage (raw Ashby dict OR canonical AtsInterviewStage) to a
    common {id, title, type, order} view. Returns None for unusable input."""
    if isinstance(s, AtsInterviewStage):
        return {
            "id": s.stage_id,
            "title": s.title,
            "type": s.type,
            "order": s.order,
        }
    if isinstance(s, dict):
        sid = s.get("id") or s.get("stage_id")
        if not sid:
            return None
        return {
            "id": sid,
            "title": s.get("title"),
            "type": s.get("type"),
            "order": s.get("orderInInterviewPlan", s.get("order")) or 0,
        }
    return None


def filter_interview_stages(stages: list) -> list[dict[str, Any]]:
    """Map stages (raw Ashby dicts or AtsInterviewStage) -> seed rounds
    (interview-bearing only, ordered by stage order)."""
    views = [v for v in (_stage_view(s) for s in stages) if v is not None]
    kept = [v for v in views if v["type"] in _INTERVIEW_STAGE_TYPES]
    kept.sort(key=lambda v: v["order"] or 0)
    return [
        {
            "ats_stage_id": str(v["id"]),
            "ats_stage_name": v["title"] or "",
            "name": v["title"] or "Interview",
            "order": int(v["order"] or 0),
        }
        for v in kept
    ]


async def _ats_job_id_for_requisition(
    supabase, organization_id: str, requisition_id: str
) -> str | None:
    result = await (
        supabase.table("ats_entity_links")
        .select("ats_id")
        .eq("organization_id", str(organization_id))
        .eq("native_type", "requisition")
        .eq("native_id", str(requisition_id))
        .eq("ats_type", "job")
        .limit(1)
        .execute_async()
    )
    rows = result.data or []
    return rows[0]["ats_id"] if rows else None


async def fetch_seed_rounds(
    supabase, *, organization_id: str, requisition_id: str
) -> list[dict]:
    """Return interview-bearing seed rounds for an ATS-linked requisition.

    Best-effort: returns [] (logged) when the requisition has no ATS job link,
    the org has no active connection, the provider has no interviews adapter, or
    the stage fetch fails. Never raises — intake/publish must not break on ATS."""
    ats_job_id = await _ats_job_id_for_requisition(
        supabase, organization_id, requisition_id
    )
    if not ats_job_id:
        return []
    try:
        bundle = await get_ats_provider(supabase, organization_id)
    except AtsNotConnectedError:
        return []
    interviews = getattr(bundle, "interviews", None)
    if interviews is None:
        return []
    try:
        stages = await interviews.fetch_job_stages(ats_job_id)
    except Exception as exc:  # noqa: BLE001 — best-effort; never break intake
        logger.warning(
            "ats_plan_seed_fetch_failed",
            requisition_id=str(requisition_id),
            ats_job_id=ats_job_id,
            error=str(exc),
        )
        return []
    return filter_interview_stages(stages or [])
