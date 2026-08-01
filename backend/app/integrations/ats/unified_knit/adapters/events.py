"""Knit sync-event eventData → canonical models.

eventData is keyed by subscribed data model (job: info/departments/offices/
hiringManagers/recruiters/stages; application: info/currentStage/rejection/...).
Inner shapes match the REST wire models, so we revalidate through them.
Returns None when the `info` model is absent (e.g. partial subscriptions or
record.deleted remnants) — callers treat that as unprocessable-with-note.
"""

from __future__ import annotations

from app.integrations.ats.core.models import AtsApplication, AtsJob
from app.integrations.ats.unified_knit.apis.candidates.mapping import (
    to_ats_application,
)
from app.integrations.ats.unified_knit.apis.candidates.wire_models import (
    KnitApplication,
)
from app.integrations.ats.unified_knit.apis.jobs.mapping import to_ats_job
from app.integrations.ats.unified_knit.apis.jobs.wire_models import KnitJob


def _unwrap(value: dict | None, key: str) -> dict | None:
    """Tolerate both `{id,text}` and `{<key>: {id,text}}` model fragments —
    the docs show both nestings for stage/rejection event models."""
    if isinstance(value, dict) and key in value and isinstance(value[key], dict):
        return value[key]
    return value if isinstance(value, dict) else None


def parse_job_event(event_data: dict) -> AtsJob | None:
    info = event_data.get("info")
    if not isinstance(info, dict) or not info.get("id"):
        return None
    wire = KnitJob.model_validate(
        {
            "info": info,
            "departments": event_data.get("departments"),
            "offices": event_data.get("offices"),
            "hiringManagers": event_data.get("hiringManagers"),
            "recruiters": event_data.get("recruiters"),
            "stages": event_data.get("stages"),
        }
    )
    return to_ats_job(wire)


def parse_application_event(event_data: dict) -> AtsApplication | None:
    info = event_data.get("info")
    if not isinstance(info, dict) or not info.get("id"):
        return None
    wire = KnitApplication.model_validate(
        {
            "info": info,
            "currentStage": _unwrap(event_data.get("currentStage"), "currentStage"),
            "rejection": _unwrap(event_data.get("rejection"), "rejection"),
        }
    )
    return to_ats_application(wire)
