from app.services.ats_enrichment.cortex_mapping import to_cortex_payload


def test_extracts_only_handler_fields():
    profile = {
        "resume": {
            "skills": ["Python", "SQL"],
            "domains": ["Backend"],
            "seniority": "senior",
            "total_experience_years": 5,
            "work_history": [
                {"title": "Eng", "company": "Acme", "highlights": ["built X"], "is_current": True},
                {"title": "No company entry"},  # dropped — no company
            ],
        },
        "ats": {"location": "San Francisco, CA"},
    }
    p = to_cortex_payload(
        candidate_id="c1", candidate_name="Jane", status="active", profile=profile
    )
    assert p["candidate_id"] == "c1"
    assert p["candidate_name"] == "Jane"
    assert p["skills"] == ["Python", "SQL"]
    assert p["domains"] == ["Backend"]
    assert p["location"] == "San Francisco, CA"
    assert p["seniority"] == "senior"
    assert len(p["work_history"]) == 1
    assert p["work_history"][0]["company"] == "Acme"


def test_includes_requisition_and_pipeline_fields():
    profile = {
        "resume": {"skills": ["SQL"]},
        "ats": {"location": "Bengaluru", "applied_at": "2026-06-12T20:33:28Z",
                "stage": {"id": "assessment", "name": "Assessment"}},
    }
    p = to_cortex_payload(
        candidate_id="c1", candidate_name="Robin", status="active", profile=profile,
        requisition_id="req-1", requisition_title="Senior Software Engineer",
        requisition_status="intake_pending",
    )
    assert p["requisition_id"] == "req-1"
    assert p["requisition_title"] == "Senior Software Engineer"
    assert p["requisition_status"] == "intake_pending"
    assert p["stage"] == "Assessment"
    assert p["applied_at"] == "2026-06-12T20:33:28Z"


def test_empty_profile_is_safe():
    p = to_cortex_payload(candidate_id="c1", candidate_name=None, status=None, profile={})
    assert p["skills"] == [] and p["domains"] == [] and p["work_history"] == []
    assert p["location"] is None


def test_normalize_recommendation_and_evaluation_payload():
    from app.services.ats_enrichment.cortex_mapping import (
        normalize_recommendation, to_evaluation_payload,
    )
    from app.integrations.ats.core.models import AtsScorecard, AtsScorecardAttribute

    assert normalize_recommendation(4) == "strong_yes"
    assert normalize_recommendation(3) == "yes"
    assert normalize_recommendation(2) == "no"
    assert normalize_recommendation(1) == "strong_no"
    assert normalize_recommendation("Strong Yes") == "strong_yes"
    assert normalize_recommendation(None) is None
    # Ashby ValueSelect submits string-numeric "4".."1"
    assert normalize_recommendation("4") == "strong_yes"
    assert normalize_recommendation("1") == "strong_no"
    # robust to camelCase / no-separator Ashby ValueSelect strings
    assert normalize_recommendation("StrongYes") == "strong_yes"
    assert normalize_recommendation("StrongNo") == "strong_no"
    assert normalize_recommendation("No Decision") == "maybe"
    assert normalize_recommendation("Definitely Not") == "strong_no"
    assert normalize_recommendation("totally unknown label") is None

    cards = [AtsScorecard(id="fb1", interviewer_id="u1", interviewer_name="Mark",
                          recommendation=4,
                          attributes=[AtsScorecardAttribute(name="System Design", rating=3, note="solid")])]
    payload = to_evaluation_payload(candidate_id="c1", candidate_name="Jenna",
                                    status="active", scorecards=cards)
    assert payload["candidate_id"] == "c1"
    ev = payload["evaluations"][0]
    assert ev["interviewer_id"] == "u1" and ev["recommendation"] == "strong_yes"
    assert ev["attributes"][0] == {"name": "System Design", "rating": "yes", "note": "solid"}

    # Non-rating Ashby form fields (booleans, free-text, non-rating ValueSelects) must
    # NOT become Cortex competencies: their rating normalizes to None and is dropped,
    # while a real overall rating ("4"→strong_yes) is kept.
    mixed = [AtsScorecard(
        id="fb2", interviewer_id="u2", interviewer_name="Willie", recommendation="4",
        attributes=[
            AtsScorecardAttribute(name="Compensation Expectation", rating="below_band"),
            AtsScorecardAttribute(name="Willing to relocate?", rating=True),
            AtsScorecardAttribute(name="Communication", rating="3", note="clear"),
        ],
    )]
    mixed_ev = to_evaluation_payload(candidate_id="c2", candidate_name="Pat",
                                     status="active", scorecards=mixed)["evaluations"][0]
    assert mixed_ev["recommendation"] == "strong_yes"
    assert mixed_ev["attributes"] == [{"name": "Communication", "rating": "yes", "note": "clear"}]


def test_normalize_recommendation_workable_thumbs():
    from app.services.ats_enrichment.cortex_mapping import normalize_recommendation
    assert normalize_recommendation("positive") == "yes"
    assert normalize_recommendation("negative") == "no"
    assert normalize_recommendation("neutral") == "maybe"
