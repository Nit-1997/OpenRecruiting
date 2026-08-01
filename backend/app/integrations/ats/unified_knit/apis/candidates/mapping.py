"""Pure wire→canonical mapping for candidates/applications."""

from app.integrations.ats.core.models import (
    AtsApplication,
    AtsAttachment,
    AtsCandidate,
    AtsContactPoint,
    AtsQuestionResponse,
    AtsRejection,
    AtsStageRef,
)
from app.integrations.ats.unified_knit.apis.candidates.wire_models import (
    KnitAnswer,
    KnitApplication,
    KnitCandidate,
)


def _normalize_answer(answer: KnitAnswer | None) -> str | None:
    """Collapse Knit's typed answer object into a single display string."""
    if answer is None:
        return None
    if answer.text:
        return answer.text
    if answer.selected_option:
        return answer.selected_option
    if answer.selected_options:
        return ", ".join(answer.selected_options)
    if answer.number_value is not None:
        return str(answer.number_value)
    if answer.rating_value is not None:
        return str(answer.rating_value)
    if answer.date_value:
        return answer.date_value
    return None


def to_ats_candidate(wire: KnitCandidate) -> AtsCandidate:
    return AtsCandidate(
        id=wire.id,
        first_name=wire.first_name,
        last_name=wire.last_name,
        emails=[
            AtsContactPoint(type=e.type, value=e.email)
            for e in (wire.emails or [])
            if e.email
        ],
        phones=[
            AtsContactPoint(type=p.type, value=p.phone_number)
            for p in (wire.phones or [])
            if p.phone_number
        ],
        links=list(wire.links or []),
        location=wire.location,
    )


def to_ats_application(wire: KnitApplication) -> AtsApplication:
    stage = wire.current_stage
    rejection = wire.rejection
    return AtsApplication(
        id=wire.info.id,
        status=wire.info.status,
        candidate=to_ats_candidate(wire.info.candidate),
        job_id=wire.info.job_id,
        applied_at=wire.info.applied_at,
        updated_at=wire.info.updated_at,
        current_stage=AtsStageRef(id=stage.id, name=stage.text) if stage else None,
        rejection=AtsRejection(
            id=rejection.id, reason=rejection.text, rejected_at=rejection.rejected_at
        )
        if rejection
        else None,
        attachments=[
            AtsAttachment(type=a.type, name=a.name, url=a.link)
            for a in (wire.attachments or [])
            if a.link
        ],
        question_responses=[
            AtsQuestionResponse(
                question=q.question_text,
                type=q.question_type,
                answer=_normalize_answer(q.answer),
            )
            for q in (wire.question_responses or [])
        ],
    )
