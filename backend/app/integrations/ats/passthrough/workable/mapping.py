"""Pure Workable-native wire→canonical mapping (candidates + rating activities)."""

from app.integrations.ats.core.models import (
    AtsApplication, AtsAttachment, AtsCandidate, AtsContactPoint, AtsScorecard, AtsStageRef,
)


def _location_str(loc) -> str | None:
    if not loc:
        return None
    if isinstance(loc, str):
        return loc
    if isinstance(loc, dict):
        parts = [loc.get("city"), loc.get("region"), loc.get("country")]
        joined = ", ".join(p for p in parts if p)
        return joined or (loc.get("location_str") or None)
    return None


def candidate_to_application(application_id: str, c: dict) -> AtsApplication:
    if c.get("disqualified"):
        status = "REJECTED"
    elif c.get("hired_at"):
        status = "HIRED"
    else:
        status = "ACTIVE"
    emails = [AtsContactPoint(value=c["email"])] if c.get("email") else []
    phones = [AtsContactPoint(value=c["phone"])] if c.get("phone") else []
    links = [
        sp["url"] for sp in (c.get("social_profiles") or [])
        if isinstance(sp, dict) and sp.get("url")
    ]
    stage = c.get("stage")
    return AtsApplication(
        id=application_id,
        status=status,
        candidate=AtsCandidate(
            id=c.get("id") or application_id,
            first_name=c.get("firstname"), last_name=c.get("lastname"),
            emails=emails, phones=phones, links=links, social_links=list(links),
            location=_location_str(c.get("location")),
            position=c.get("headline"),
        ),
        applied_at=c.get("created_at"),
        current_stage=AtsStageRef(name=stage) if stage else None,
        attachments=(
            [AtsAttachment(type="RESUME", url=c["resume_url"])] if c.get("resume_url") else []
        ),
    )


def rating_activity_to_scorecard(act: dict) -> AtsScorecard:
    member = act.get("member") or {}
    rating = act.get("rating") or {}
    return AtsScorecard(
        id=act.get("id"),
        interviewer_id=member.get("id"),
        interviewer_name=member.get("name"),
        recommendation=rating.get("score"),
        submitted_at=act.get("created_at"),
        summary=act.get("body"),
        attributes=[],
    )
