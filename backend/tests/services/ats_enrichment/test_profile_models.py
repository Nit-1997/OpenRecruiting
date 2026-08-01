from app.services.ats_enrichment.profile_models import ResumeProfile


def test_defaults_are_empty():
    p = ResumeProfile()
    assert p.summary == ""
    assert p.total_experience_years == 0.0
    assert p.skills == [] and p.domains == [] and p.links == {}
    assert p.work_history == [] and p.education == []


def test_parses_nested_work_and_education():
    p = ResumeProfile.model_validate(
        {
            "summary": "Senior analyst",
            "skills": ["FP&A", "SQL"],
            "work_history": [{"title": "Director", "company": "Acme", "is_current": True}],
            "education": [{"degree": "MBA", "institution": "X"}],
        }
    )
    assert p.skills == ["FP&A", "SQL"]
    assert p.work_history[0].company == "Acme" and p.work_history[0].is_current is True
    assert p.education[0].degree == "MBA"


def test_ignores_unknown_keys():
    p = ResumeProfile.model_validate({"summary": "s", "bogus": 123})
    assert p.summary == "s"
