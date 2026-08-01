from app.integrations.ats.adapters.requisitions import (
    to_requisition_fields,
    to_update_diff,
)
from app.integrations.ats.core.models import AtsJob, AtsOffice


def make_job(**over):
    base = dict(id="j1", title="SWE", status="OPEN")
    base.update(over)
    return AtsJob(**base)


def test_fields_defaults_for_not_null_columns():
    fields = to_requisition_fields(make_job())
    assert fields["role_title"] == "SWE"
    assert fields["role_location"] == "Not specified"
    assert fields["experience_min_years"] == 0
    assert fields["ats_job_id"] == "j1"
    assert "must_have_skills" not in fields


def test_fields_uses_first_office_location():
    job = make_job(offices=[AtsOffice(location="SF"), AtsOffice(location="NY")])
    assert to_requisition_fields(job)["role_location"] == "SF"


def test_fields_skips_empty_office_locations():
    job = make_job(offices=[AtsOffice(location=None), AtsOffice(location="NY")])
    assert to_requisition_fields(job)["role_location"] == "NY"


def test_update_diff_returns_changed_fields_only():
    job = make_job(title="SWE II", description="new jd")
    existing = {
        "role_title": "SWE",
        "role_location": "Not specified",
        "job_description": "old jd",
        "experience_min_years": 0,
        "experience_max_years": None,
    }
    diff = to_update_diff(job, existing)
    assert diff == {
        "role_title": "SWE II",
        "job_description": "new jd",
        "ats_job_id": "j1",
    }


def test_update_diff_empty_when_no_changes():
    job = make_job(description=None)
    existing = {
        "role_title": "SWE",
        "role_location": "Not specified",
        "job_description": None,
        "experience_min_years": 0,
        "experience_max_years": None,
    }
    assert to_update_diff(job, existing) == {}
