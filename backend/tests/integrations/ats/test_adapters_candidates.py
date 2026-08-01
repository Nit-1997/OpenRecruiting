from app.integrations.ats.adapters.candidates import (
    CandidateSkip,
    to_candidate_fields,
    to_fast_lane_profile,
)
from app.integrations.ats.core.models import (
    AtsApplication,
    AtsCandidate,
    AtsContactPoint,
)


def make_app(status="ACTIVE", **cand_over):
    cand = dict(
        id="c1",
        first_name="Emily",
        last_name="Watson",
        emails=[AtsContactPoint(value="emily@x.co")],
        phones=[AtsContactPoint(value="+1")],
    )
    cand.update(cand_over)
    return AtsApplication(
        id="a1", status=status, candidate=AtsCandidate(**cand), job_id="j1"
    )


def test_maps_full_candidate():
    fields = to_candidate_fields(make_app())
    assert fields == {
        "name": "Emily Watson",
        "email": "emily@x.co",
        "phone": "+1",
        "status": "active",
        "ats_job_id": "j1",
    }


def test_status_mapping():
    assert to_candidate_fields(make_app())["status"] == "active"
    assert to_candidate_fields(make_app(status="HIRED"))["status"] == "hired"
    assert to_candidate_fields(make_app(status="REJECTED"))["status"] == "rejected"
    assert to_candidate_fields(make_app(status="SOMETHING_NEW"))["status"] == "active"


def test_first_name_only_still_maps():
    fields = to_candidate_fields(make_app(last_name=None))
    assert fields["name"] == "Emily"


def test_skip_no_email():
    skip = to_candidate_fields(make_app(emails=[]))
    assert isinstance(skip, CandidateSkip) and skip.reason == "no_email"
    assert skip.ats_application_id == "a1"


def test_skip_no_name():
    skip = to_candidate_fields(make_app(first_name=None, last_name=None))
    assert isinstance(skip, CandidateSkip) and skip.reason == "no_name"


def test_fast_lane_profile_keeps_location_links_applied_at():
    app_ = AtsApplication(
        id="a1",
        status="ACTIVE",
        candidate=AtsCandidate(
            id="c1",
            first_name="Emily",
            emails=[AtsContactPoint(value="emily@x.co")],
            location="Sunnyvale, California, US",
            links=["https://linkedin.com/in/emily"],
        ),
        job_id="j1",
        applied_at="2026-06-12T20:33:28Z",
    )
    assert to_fast_lane_profile(app_) == {
        "ats": {
            "location": "Sunnyvale, California, US",
            "applied_at": "2026-06-12T20:33:28Z",
            "links": ["https://linkedin.com/in/emily"],
        }
    }


def test_fast_lane_profile_empty_when_no_signals():
    app_ = AtsApplication(
        id="a1",
        status="ACTIVE",
        candidate=AtsCandidate(id="c1", first_name="Bo"),
    )
    assert to_fast_lane_profile(app_) == {}
