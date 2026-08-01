"""Merge the resume-derived ResumeProfile with the ATS signals from a fresh
application.get pull into the single candidates.profile JSONB blob (spec §3).
Pure + null-safe: resume may be None (no/unreadable resume), in which case the
profile still carries everything the ATS delivered."""

from __future__ import annotations

from datetime import datetime, timezone

from app.integrations.ats.core.models import AtsApplication
from app.services.ats_enrichment.profile_models import ResumeProfile

SCHEMA_VERSION = 1


def build_profile(
    resume: ResumeProfile | None, application: AtsApplication, *, model: str
) -> dict:
    candidate = application.candidate

    ats: dict = {}
    if candidate.location:
        ats["location"] = candidate.location
    if application.applied_at:
        ats["applied_at"] = application.applied_at
    if application.current_stage:
        ats["stage"] = {
            "id": application.current_stage.id,
            "name": application.current_stage.name,
        }
    if application.rejection and (
        application.rejection.reason or application.rejection.rejected_at
    ):
        ats["rejection"] = {
            "reason": application.rejection.reason,
            "rejected_at": application.rejection.rejected_at,
        }
    if application.question_responses:
        ats["screening_qa"] = [
            {"question": q.question, "type": q.type, "answer": q.answer}
            for q in application.question_responses
        ]
    if candidate.links:
        ats["links"] = list(candidate.links)

    return {
        "schema_version": SCHEMA_VERSION,
        "resume": resume.model_dump() if resume is not None else None,
        "ats": ats,
        "links": dict(resume.links) if resume and resume.links else {},
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "source": "resume+ats" if resume is not None else "ats",
    }
