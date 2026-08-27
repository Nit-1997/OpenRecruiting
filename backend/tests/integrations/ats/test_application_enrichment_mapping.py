"""Wire → canonical mapping of the enrichment-bearing application.get fields:
resume attachment (link) + typed screening questionResponses. Field paths
verified live against the connected Workable account (2026-06-12)."""

from app.integrations.ats.unified_knit.apis.candidates.mapping import (
    to_ats_application,
)
from app.integrations.ats.unified_knit.apis.candidates.wire_models import (
    KnitApplication,
)

FULL_GET = {
    "info": {
        "id": "261d85fd",
        "status": "REJECTED",
        "candidate": {
            "id": "261d85fd",
            "firstName": "Alex",
            "lastName": "Rivera",
            "emails": [{"type": "NOT_SPECIFIED", "email": "alex.rivera@example.com"}],
            "location": "Sunnyvale, California, United States",
        },
        "jobId": "68DF417FCE",
        "appliedAt": "2026-06-12T20:33:28Z",
    },
    "currentStage": {"id": "interview", "text": "Interview"},
    "rejection": {"id": None, "text": "Doesn't have required experience",
                  "rejectedAt": "2026-06-12T23:10:30.395Z"},
    "attachments": [
        {"type": "RESUME", "name": None,
         "link": "https://workablehr.s3.amazonaws.com/uploads/x/resume.pdf?X-Amz-Expires=60000"},
        {"type": "COVER_LETTER", "name": None, "link": None},
    ],
    "questionResponses": [
        {"questionType": "YES_NO", "questionText": "Need Visa",
         "answer": {"text": "NO"}},
        {"questionType": "MULTIPLE_CHOICE", "questionText": "Seniority",
         "answer": {"selectedOptions": ["Senior", "Staff"]}},
    ],
}


def test_resume_attachment_maps_link_to_url():
    app_ = to_ats_application(KnitApplication.model_validate(FULL_GET))
    resumes = [a for a in app_.attachments if a.type == "RESUME"]
    assert len(resumes) == 1
    assert resumes[0].url.startswith("https://workablehr.s3.amazonaws.com/")
    # the cover-letter attachment with link=None is dropped
    assert all(a.url for a in app_.attachments)


def test_question_responses_normalize_answer():
    app_ = to_ats_application(KnitApplication.model_validate(FULL_GET))
    qa = {q.question: q for q in app_.question_responses}
    assert qa["Need Visa"].type == "YES_NO"
    assert qa["Need Visa"].answer == "NO"
    assert qa["Seniority"].answer == "Senior, Staff"


def test_rejection_and_stage_still_map():
    app_ = to_ats_application(KnitApplication.model_validate(FULL_GET))
    assert app_.rejection.reason == "Doesn't have required experience"
    assert app_.current_stage.name == "Interview"


def test_null_collections_map_to_empty():
    minimal = {"info": FULL_GET["info"]}
    app_ = to_ats_application(KnitApplication.model_validate(minimal))
    assert app_.attachments == []
    assert app_.question_responses == []
