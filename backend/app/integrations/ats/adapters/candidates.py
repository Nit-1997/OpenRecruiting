"""AtsApplication → candidates-row fields, or CandidateSkip with the reason.
candidates.email and .name are NOT NULL — unmappable applications are skipped
EXPLICITLY and counted, never silently dropped."""

from dataclasses import dataclass

from app.integrations.ats.core.models import AtsApplication

_STATUS_MAP = {"ACTIVE": "active", "HIRED": "hired", "REJECTED": "rejected"}


@dataclass(slots=True)
class CandidateSkip:
    reason: str  # 'no_email' | 'no_name'
    ats_application_id: str


def to_candidate_fields(application: AtsApplication) -> dict | CandidateSkip:
    candidate = application.candidate
    name = " ".join(
        part for part in (candidate.first_name, candidate.last_name) if part
    ).strip()
    if not name:
        return CandidateSkip("no_name", application.id)
    if not candidate.emails:
        return CandidateSkip("no_email", application.id)
    return {
        "name": name,
        "email": candidate.emails[0].value,
        "phone": candidate.phones[0].value if candidate.phones else None,
        "status": _STATUS_MAP.get(application.status, "active"),
        "ats_job_id": application.job_id,
    }


def to_fast_lane_profile(application: AtsApplication) -> dict:
    """The cheap candidate signals that ride inside the webhook event itself
    (location/links/applied_at) — persisted to candidates.profile at sync time,
    BEFORE the throttled worker pulls the resume. Returns the partial
    {"ats": {...}} blob that ats_upsert_candidate shallow-merges into profile
    (only while enrichment_status != 'done', so the worker's full profile —
    which also carries these — is never clobbered)."""
    candidate = application.candidate
    ats: dict = {}
    if candidate.location:
        ats["location"] = candidate.location
    if application.applied_at:
        ats["applied_at"] = application.applied_at
    if candidate.links:
        ats["links"] = list(candidate.links)
    return {"ats": ats} if ats else {}
