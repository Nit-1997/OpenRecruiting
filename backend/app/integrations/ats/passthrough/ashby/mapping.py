"""Pure Ashby-native wire→canonical mapping (candidate.info / application.info)."""

from app.integrations.ats.core.models import (
    AtsApplication, AtsAttachment, AtsCandidate, AtsContactPoint, AtsStageRef,
)


def _split_name(full: str | None) -> tuple[str | None, str | None]:
    if not full or not full.strip():
        return None, None
    parts = full.strip().split()
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def candidate_from_info(candidate_id: str, results: dict) -> AtsCandidate:
    first, last = _split_name(results.get("name"))
    emails = [
        AtsContactPoint(type=e.get("type"), value=e["value"])
        for e in (results.get("emailAddresses") or []) if e.get("value")
    ]
    phones = [
        AtsContactPoint(type=p.get("type"), value=p["value"])
        for p in (results.get("phoneNumbers") or []) if p.get("value")
    ]
    links = [
        s["url"] for s in (results.get("socialLinks") or [])
        if isinstance(s, dict) and s.get("url")
    ]
    return AtsCandidate(
        id=candidate_id, first_name=first, last_name=last,
        emails=emails, phones=phones, links=links, social_links=list(links),
        position=results.get("position"), company=results.get("company"),
        school=results.get("school"),
    )


def attachment_from_handle(resume_url: str | None, resume_name: str | None) -> list[AtsAttachment]:
    if not resume_url:
        return []
    return [AtsAttachment(type="RESUME", name=resume_name, url=resume_url)]


def application_from_infos(
    application_id: str, candidate_results: dict, app_results: dict | None,
    *, resume_url: str | None, resume_name: str | None,
) -> AtsApplication:
    candidate = candidate_from_info(
        candidate_results.get("id") or application_id,
        candidate_results,
    )
    app_results = app_results or {}
    info = app_results.get("info") or {}
    stage_obj = app_results.get("currentInterviewStage")
    current_stage = (
        AtsStageRef(id=stage_obj.get("id"), name=stage_obj.get("title") or stage_obj.get("name"))
        if isinstance(stage_obj, dict) else None
    )
    return AtsApplication(
        id=application_id,
        status=app_results.get("status") or info.get("status") or "ACTIVE",
        candidate=candidate,
        job_id=info.get("jobId"),
        applied_at=info.get("appliedAt"),
        current_stage=current_stage,
        attachments=attachment_from_handle(resume_url, resume_name),
    )
