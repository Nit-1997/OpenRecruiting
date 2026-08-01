import pytest
from pydantic import ValidationError

from scripts._fixture_schema import Fixture


def _minimal_valid_payload() -> dict:
    return {
        "fixture_version": 1,
        "round_id": "fbdcfddc-4887-4b1c-b16f-7c9bf99f004c",
        "captured_at": "2026-05-13T00:00:00Z",
        "source_environment": "production",
        "redaction": {"candidate_name": "Candidate", "interviewer_names": {}},
        "feedback_source": {
            "source": "scorecard",
            "scorecard_transcript": "...",
            "has_interview_transcript": True,
        },
        "questions": [
            {"id": "q1", "question_number": 1, "heading": "X", "description": "Y"}
        ],
        "role_context": {
            "role": "Engineer",
            "seniority": "5-8 Years",
            "location": "Remote",
            "must_have_skills": [],
            "good_to_have_skills": [],
            "intake_notes": "",
            "job_description": "",
        },
        "transcript": {
            "feedback_transcript": "",
            "segments": [],
            "feedback_start_timestamp": None,
        },
        "baseline_outputs": {
            "rating": None,
            "summary": None,
            "question_summaries": {},
            "competency_snapshots": None,
        },
    }


def test_fixture_accepts_minimal_valid_payload():
    fixture = Fixture(**_minimal_valid_payload())
    assert fixture.round_id == "fbdcfddc-4887-4b1c-b16f-7c9bf99f004c"
    assert fixture.feedback_source.source == "scorecard"


def test_fixture_rejects_unknown_source():
    payload = _minimal_valid_payload()
    payload["feedback_source"]["source"] = "carrier-pigeon"
    with pytest.raises(ValidationError):
        Fixture(**payload)


def test_fixture_rejects_missing_round_id():
    payload = _minimal_valid_payload()
    del payload["round_id"]
    with pytest.raises(ValidationError):
        Fixture(**payload)
