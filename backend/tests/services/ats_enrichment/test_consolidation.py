from app.integrations.ats.core.models import (
    AtsApplication,
    AtsCandidate,
    AtsQuestionResponse,
    AtsRejection,
    AtsStageRef,
)
from app.services.ats_enrichment.consolidation import build_profile
from app.services.ats_enrichment.profile_models import ResumeProfile


def _app(**over):
    cand = AtsCandidate(
        id="c1",
        first_name="Nitin",
        location=over.pop("location", "Sunnyvale, CA"),
        links=over.pop("links", ["https://linkedin.com/in/x"]),
    )
    return AtsApplication(
        id="a1",
        status=over.pop("status", "REJECTED"),
        candidate=cand,
        applied_at="2026-06-12T20:33:28Z",
        current_stage=AtsStageRef(id="interview", name="Interview"),
        rejection=AtsRejection(reason="Doesn't have required experience", rejected_at="t"),
        question_responses=[AtsQuestionResponse(question="Need Visa", type="YES_NO", answer="NO")],
    )


def test_full_profile_merges_resume_and_ats():
    resume = ResumeProfile(summary="Senior FP&A", skills=["FP&A"], links={"linkedin": "u"})
    p = build_profile(resume, _app(), model="claude-sonnet-4-6")
    assert p["schema_version"] == 1
    assert p["resume"]["summary"] == "Senior FP&A"
    assert p["ats"]["location"] == "Sunnyvale, CA"
    assert p["ats"]["applied_at"] == "2026-06-12T20:33:28Z"
    assert p["ats"]["stage"] == {"id": "interview", "name": "Interview"}
    assert p["ats"]["rejection"]["reason"] == "Doesn't have required experience"
    assert p["ats"]["screening_qa"][0] == {
        "question": "Need Visa", "type": "YES_NO", "answer": "NO"
    }
    assert p["ats"]["links"] == ["https://linkedin.com/in/x"]
    assert p["links"] == {"linkedin": "u"}
    assert p["model"] == "claude-sonnet-4-6"
    assert p["source"] == "resume+ats"
    assert "extracted_at" in p


def test_profile_without_resume_still_carries_ats():
    p = build_profile(None, _app(), model="m")
    assert p["resume"] is None
    assert p["ats"]["rejection"]["reason"] == "Doesn't have required experience"
    assert p["links"] == {}
    assert p["source"] == "ats"


def test_minimal_application_has_empty_ats():
    app_ = AtsApplication(
        id="a1", status="ACTIVE",
        candidate=AtsCandidate(id="c1", first_name="Bo", location=None, links=[]),
    )
    p = build_profile(None, app_, model="m")
    assert p["ats"] == {}
