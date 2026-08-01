"""AtsJob → requisitions-row fields. Pure; NOT-NULL columns get explicit
defaults (role_location, experience_min_years). ats_job_id rides along for
the candidate-lane requisition resolution and is NOT a requisitions column."""

from app.integrations.ats.core.models import AtsJob

_DEFAULT_LOCATION = "Not specified"
_DIFFABLE = (
    "role_title",
    "role_location",
    "job_description",
    "experience_min_years",
    "experience_max_years",
)


def to_requisition_fields(job: AtsJob) -> dict:
    return {
        "role_title": job.title,
        "role_location": next(
            (o.location for o in job.offices if o.location), _DEFAULT_LOCATION
        ),
        "experience_min_years": 0,
        "experience_max_years": None,
        "job_description": job.description,
        "ats_job_id": job.id,
    }


def to_update_diff(job: AtsJob, existing: dict) -> dict:
    """Changed-fields-only payload for ats_dirty review. Empty dict = no diff."""
    candidate_fields = to_requisition_fields(job)
    diff = {
        key: value
        for key, value in candidate_fields.items()
        if key in _DIFFABLE and value is not None and existing.get(key) != value
    }
    if diff:
        diff["ats_job_id"] = job.id
    return diff
