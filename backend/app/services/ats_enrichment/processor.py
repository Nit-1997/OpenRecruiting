"""Enrich one candidate: resolve its ATS ids → re-pull application.get (fresh
presigned resume URL + screening Q&A + rejection) → download/parse/extract the
resume → durable-copy the bytes → consolidate → persist via ats_enrich_candidate
→ best-effort Cortex push. External boundaries are injectable for tests.

Outcome: returns 'done' (ats_enrich_candidate set status='done') or 'skipped'
(not an ATS candidate / no integration). Raises on a real failure so the worker
can retry/park."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import structlog

from app.api.v2.core.rpc import call_rpc
from app.config import get_settings
from app.integrations.ats.core.models import AtsApplication
from app.integrations.ats.core.registry import get_ats_provider
from app.services.ats_enrichment.consolidation import build_profile
from app.services.ats_enrichment.cortex_mapping import (
    to_cortex_payload,
    to_evaluation_payload,
)
from app.services.ats_enrichment.cortex_push import (
    push_candidate_evaluation,
    push_candidate_profile,
)
from app.services.ats_enrichment.profile_models import ResumeProfile
from app.services.ats_enrichment.resume_text import (
    download_resume_bytes,
    parse_resume_text,
)
from app.services.ats_enrichment.signal_extractor import extract_resume_profile

logger = structlog.get_logger(__name__)


async def _safe_upload(upload_fn, data: bytes, candidate_id: str, filename: str | None):
    if upload_fn is None:
        from app.services.s3_service import upload_resume

        upload_fn = upload_resume
    try:
        return await asyncio.to_thread(upload_fn, data, candidate_id, filename)
    except Exception as exc:  # noqa: BLE001 — durable copy is best-effort
        logger.warning("resume_upload_failed", error=str(exc))
        return None


async def process_candidate(
    supabase,
    candidate_row: dict,
    *,
    fetch_application: Callable[[str, str, str], Awaitable[AtsApplication]] | None = None,
    download_resume: Callable[[str, int], Awaitable[tuple[bytes, str] | None]] | None = None,
    extract_profile: Callable[[str, str], Awaitable[ResumeProfile]] | None = None,
    upload_resume_fn: Callable[[bytes, str, str | None], str | None] | None = None,
    push_cortex: Callable[..., Awaitable[bool]] | None = None,
    model: str | None = None,
) -> str:
    settings = get_settings()
    model = model or settings.RESUME_EXTRACTION_MODEL
    push_cortex = push_cortex or push_candidate_profile

    candidate_id = candidate_row["id"]

    link_res = await (
        supabase.table("ats_entity_links")
        .select("ats_id, ats_candidate_id, connection_id, organization_id, provider")
        .eq("native_type", "candidate")
        .eq("native_id", candidate_id)
        .limit(1)
        .execute_async()
    )
    if not link_res.data:
        return "skipped"  # not an ATS candidate (e.g. OpenRecruiting-created) — nothing to pull
    link = link_res.data[0]
    org_id = link["organization_id"]
    application_id = link["ats_id"]
    ats_candidate_id = link.get("ats_candidate_id") or application_id

    # Resolves the org's ACTIVE ATS connection. Safe in SS1 because a candidate is
    # enqueued (enrichment_status='pending') only by the active connection's own sync
    # (ats_upsert_candidate, migration 128), so link.connection_id == the active
    # connection at every reachable enqueue. SS1b (multi-provider / re-enqueue of a
    # stale-provider link) MUST resolve by link.connection_id instead — and handle a
    # deactivated integration's auth.
    bundle = await get_ats_provider(supabase, org_id)
    if fetch_application is not None:
        application = await fetch_application(
            bundle.knit_integration_id, application_id, ats_candidate_id
        )
    else:
        application = await bundle.candidates.get_application(
            application_id, ats_candidate_id
        )

    resume_profile: ResumeProfile | None = None
    resume_url: str | None = None
    existing_resume = (candidate_row.get("profile") or {}).get("resume")
    if existing_resume:
        # Resume doesn't change — a re-enrichment (e.g. status→rejected) refreshes
        # ATS signals only; never re-download or re-run the LLM.
        try:
            resume_profile = ResumeProfile.model_validate(existing_resume)
        except Exception:  # noqa: BLE001
            resume_profile = None
    else:
        attachment = next(
            (
                a
                for a in application.attachments
                if (a.type or "").upper() == "RESUME" and a.url
            ),
            None,
        )
        if attachment is not None:
            if download_resume is not None:
                downloaded = await download_resume(
                    attachment.url, settings.ATS_RESUME_MAX_BYTES
                )
            else:
                downloaded = await download_resume_bytes(
                    attachment.url, max_bytes=settings.ATS_RESUME_MAX_BYTES
                )
            if downloaded is not None:
                data, content_type = downloaded
                text = await parse_resume_text(data, content_type, attachment.name)
                if text:
                    if extract_profile is not None:
                        resume_profile = await extract_profile(text, model)
                    else:
                        resume_profile = await extract_resume_profile(text, model=model)
                resume_url = await _safe_upload(
                    upload_resume_fn, data, candidate_id, attachment.name
                )

    profile = build_profile(resume_profile, application, model=model)

    await call_rpc(
        supabase,
        "ats_enrich_candidate",
        {
            "p_candidate_id": candidate_id,
            "p_org_id": org_id,
            "p_profile": profile,
            "p_resume_url": resume_url,
        },
    )

    req_id = candidate_row.get("requisition_id")
    req_title: str | None = None
    req_status: str | None = None
    if req_id:
        req_res = await (
            supabase.table("requisitions")
            .select("role_title, status")
            .eq("id", req_id)
            .limit(1)
            .execute_async()
        )
        if req_res.data:
            req_title = req_res.data[0].get("role_title")
            req_status = req_res.data[0].get("status")

    payload = to_cortex_payload(
        candidate_id=candidate_id,
        candidate_name=candidate_row.get("name"),
        status=candidate_row.get("status"),
        profile=profile,
        requisition_id=req_id,
        requisition_title=req_title,
        requisition_status=req_status,
    )
    await push_cortex(org_id=org_id, candidate_id=candidate_id, payload=payload)

    # Best-effort: Ashby exposes interviewer scorecards (unified does not, so
    # bundle.scorecards is None there). Push them as a separate candidate_evaluation
    # event. The profile is already persisted — a scorecard failure must never fail
    # enrichment.
    if bundle.scorecards is not None:
        try:
            scorecards = await bundle.scorecards.fetch_scorecards(
                application_id, ats_candidate_id
            )
            if scorecards:
                eval_payload = to_evaluation_payload(
                    candidate_id=candidate_id,
                    candidate_name=candidate_row.get("name"),
                    status=candidate_row.get("status"),
                    scorecards=scorecards,
                )
                await push_candidate_evaluation(
                    org_id=org_id, candidate_id=candidate_id, payload=eval_payload
                )
        except Exception as exc:  # noqa: BLE001 — scorecards are best-effort, never fail enrichment
            logger.warning(
                "ats_scorecard_push_failed", candidate_id=candidate_id, error=str(exc)
            )
    return "done"
