"""Canonical model + error-taxonomy contracts for the ATS integrations core."""

from app.integrations.ats.core.errors import (
    AtsAuthError,
    AtsIntegrationError,
    AtsNotConnectedError,
    AtsNotSupportedError,
    AtsProviderError,
    AtsRateLimitedError,
    AtsResourceNotFoundError,
)
from app.integrations.ats.core.models import (
    AtsApplication,
    AtsCandidate,
    AtsJob,
    CandidateSearchCriteria,
    Page,
)


def test_page_is_generic_and_serializable():
    page = Page[AtsJob](items=[AtsJob(id="j1", title="SWE", status="OPEN")])
    assert page.next_page_token is None
    assert page.model_dump()["items"][0]["title"] == "SWE"


def test_job_defaults_are_empty_collections():
    job = AtsJob(id="j1", title="SWE", status="OPEN")
    assert job.stages == [] and job.offices == [] and job.recruiters == []


def test_candidate_and_application_minimal():
    cand = AtsCandidate(id="c1")
    app_ = AtsApplication(id="a1", status="ACTIVE", candidate=cand)
    assert app_.candidate.id == "c1" and app_.current_stage is None


def test_search_criteria_empty_detection():
    assert CandidateSearchCriteria().is_empty()
    assert not CandidateSearchCriteria(email="a@b.co").is_empty()


def test_error_hierarchy():
    for exc in (
        AtsAuthError,
        AtsNotSupportedError,
        AtsRateLimitedError,
        AtsProviderError,
        AtsResourceNotFoundError,
        AtsNotConnectedError,
    ):
        assert issubclass(exc, AtsIntegrationError)


def test_ats_scorecard_and_candidate_extensions():
    from app.integrations.ats.core.models import AtsScorecard, AtsScorecardAttribute, AtsCandidate

    sc = AtsScorecard(
        id="fb1", interviewer_id="u1", interviewer_name="Mark", recommendation=4,
        attributes=[AtsScorecardAttribute(name="System Design", rating=3, note="solid")],
    )
    assert sc.attributes[0].name == "System Design"

    cand = AtsCandidate(id="c1", position="Backend Engineer", company="Auction.com",
                        school="Yale", social_links=["https://linkedin.com/in/x"])
    assert cand.position == "Backend Engineer"
    assert cand.social_links == ["https://linkedin.com/in/x"]
    # backward-compat: fields default empty/None
    assert AtsCandidate(id="c2").social_links == []


def test_scorecards_port_importable():
    from app.integrations.ats.core.ports import ScorecardsPort
    assert hasattr(ScorecardsPort, "fetch_scorecards")
