"""Knit sync-event eventData → canonical models. Event payloads carry the
same inner shapes as REST, keyed by data model (info/stages/currentStage/...)."""

from app.integrations.ats.unified_knit.adapters.events import (
    parse_application_event,
    parse_job_event,
)

JOB_EVENT_DATA = {
    "info": {
        "id": "job-1",
        "title": "Frontend Engineer",
        "status": "OPEN",
        "description": "Build UIs",
    },
    "stages": [{"id": "s1", "text": "Screen"}],
    "departments": None,
    "offices": None,
}

APP_EVENT_DATA = {
    "info": {
        "id": "app-1",
        "status": "ACTIVE",
        "candidate": {
            "id": "cand-1",
            "firstName": "Emily",
            "lastName": "Watson",
            "emails": [{"type": "PERSONAL", "email": "emily@x.co"}],
            "phones": None,
            "links": None,
            "location": None,
        },
        "jobId": "job-1",
        "appliedAt": "2026-01-01T00:00:00Z",
    },
    "currentStage": {"id": "s1", "text": "Screen"},
    "rejection": None,
}

APP_EVENT_DATA_NESTED_STAGE = {
    "info": APP_EVENT_DATA["info"],
    "currentStage": {"currentStage": {"id": "s2", "text": "Onsite"}},
}


def test_parse_job_event_builds_canonical():
    job = parse_job_event(JOB_EVENT_DATA)
    assert job is not None
    assert job.id == "job-1" and job.title == "Frontend Engineer"
    assert job.stages[0].name == "Screen"


def test_parse_job_event_without_info_returns_none():
    assert parse_job_event({"stages": []}) is None
    assert parse_job_event({}) is None


def test_parse_application_event_builds_canonical():
    app_ = parse_application_event(APP_EVENT_DATA)
    assert app_ is not None
    assert app_.id == "app-1" and app_.candidate.first_name == "Emily"
    assert app_.job_id == "job-1"
    assert app_.current_stage.name == "Screen"


def test_parse_application_event_unwraps_nested_stage():
    app_ = parse_application_event(APP_EVENT_DATA_NESTED_STAGE)
    assert app_.current_stage.name == "Onsite"


def test_parse_application_event_without_info_returns_none():
    assert parse_application_event({}) is None
