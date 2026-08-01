from app.integrations.ats.passthrough.workable.mapping import (
    candidate_to_application, rating_activity_to_scorecard,
)


def test_candidate_to_application_maps_resume_and_fields():
    cand = {
        "id": "260ff56e", "firstname": "Elvie", "lastname": "Schmidt",
        "email": "elvie@example.com", "phone": "+1 555",
        "resume_url": "https://wk/resume.pdf", "stage": "Phone Screen",
        "disqualified": False, "created_at": "2026-03-01T00:00:00Z",
        "headline": "Senior Engineer",
        "skills": [{"name": "Edge"}, {"name": "Mobile devices"}],
        "social_profiles": [{"type": "linkedin", "name": "LinkedIn", "url": "https://linkedin.com/in/e"}],
        "location": {"city": "Austin", "country": "United States"},
    }
    app = candidate_to_application("app-1", cand)
    assert app.id == "app-1" and app.status == "ACTIVE"
    assert app.candidate.first_name == "Elvie" and app.candidate.last_name == "Schmidt"
    assert app.candidate.emails[0].value == "elvie@example.com"
    assert app.candidate.phones[0].value == "+1 555"
    assert app.candidate.links == ["https://linkedin.com/in/e"]
    assert app.candidate.position == "Senior Engineer"
    assert app.candidate.location == "Austin, United States"
    assert app.current_stage.name == "Phone Screen"
    assert app.applied_at == "2026-03-01T00:00:00Z"
    assert app.attachments[0].type == "RESUME" and app.attachments[0].url == "https://wk/resume.pdf"


def test_candidate_status_reflects_disqualified_and_hired():
    assert candidate_to_application("a", {"id": "c", "disqualified": True}).status == "REJECTED"
    assert candidate_to_application("a", {"id": "c", "hired_at": "2026-01-01"}).status == "HIRED"


def test_candidate_to_application_tolerates_dirty_social_profiles_and_no_resume():
    from app.integrations.ats.passthrough.workable.mapping import candidate_to_application
    app = candidate_to_application("a", {
        "id": "c",
        "social_profiles": ["bad", None, {"url": "https://ok"}],  # non-dict entries
        # no resume_url, no email/phone
    })
    assert app.candidate.links == ["https://ok"]
    assert app.attachments == []
    assert app.status == "ACTIVE"


def test_rating_activity_to_scorecard():
    act = {"id": "8bbf70d9", "action": "rating", "stage_name": "Phone Screen",
           "created_at": "2026-03-03T00:00:00Z", "member": {"id": "1ed7fc", "name": "Alexia Middleton"},
           "body": "Good", "rating": {"score": "positive", "scale": "thumbs", "grade": 1}}
    sc = rating_activity_to_scorecard(act)
    assert sc.id == "8bbf70d9"
    assert sc.interviewer_id == "1ed7fc" and sc.interviewer_name == "Alexia Middleton"
    assert sc.recommendation == "positive"
    assert sc.summary == "Good"
    assert sc.submitted_at == "2026-03-03T00:00:00Z"
    assert sc.attributes == []
