import json
from pathlib import Path

import pytest

from scripts._fixture_schema import Fixture
from scripts.normalize_fixture import normalize


def _write(tmp_path: Path, name: str, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return p


@pytest.fixture
def raw_dir_scorecard(tmp_path: Path) -> Path:
    """Mimics fixture-keerthi (scorecard path) layout."""
    _write(tmp_path, "step2_round.json", [{
        "candidate_round_id": "round-1",
        "candidate_id": "cand-1",
        "candidate_name": "Lena Ortiz",
        "scorecard_transcript": "Keith, the this is a feedback for Lena.",
        "current_rating": "strong_yes",
        "current_summary": "She fell short...",
        "current_question_summaries": {"1": "..."},
        "current_competency_snapshots": "- X: ...",
        "role_title": "PM",
        "role_location": "Bangalore",
        "experience_min_years": 2,
        "experience_max_years": 4,
        "intake_notes": None,
        "job_description": "JD body",
        "must_have_skills": [],
        "good_to_have_skills": [],
    }])
    _write(tmp_path, "step3_questions.json", [
        {"id": "q1", "question_number": 1, "heading": "B2B", "description": "..."},
    ])
    _write(tmp_path, "step4_transcript.json", [{
        "candidate_round_id": "round-1",
        "feedback_transcript": "OpenRecruiting: Hi Lena.",
        "segments": [
            {"participant": {"id": 100, "name": "Lena", "extra_data": {"teams": "..."}},
             "words": [{"text": "Hi"}]},
            {"participant": {"id": 200, "name": "Priya", "extra_data": {"teams": "..."}},
             "words": [{"text": "Hello"}]},
        ],
        "raw_transcript_url": "https://signed.s3.aws.com/secret",
    }])
    _write(tmp_path, "step5_bot.json", [{
        "feedback_started_at": "2026-05-12T07:21:57.951879+00:00",
        "joined_at": "2026-05-12T06:06:24.005341+00:00",
        "feedback_status": "partial",
    }])
    return tmp_path


def test_normalize_resolves_scorecard_source(raw_dir_scorecard: Path):
    fx = normalize(raw_dir_scorecard)
    assert fx.feedback_source.source == "scorecard"
    assert fx.feedback_source.scorecard_transcript is not None


def test_normalize_redacts_candidate_and_interviewer(raw_dir_scorecard: Path):
    fx = normalize(raw_dir_scorecard)
    # Candidate name removed from textual fields
    assert "Lena" not in fx.feedback_source.scorecard_transcript
    assert "Candidate" in fx.feedback_source.scorecard_transcript
    # Participant names replaced
    names = {seg["participant"]["name"] for seg in fx.transcript.segments}
    assert names == {"Candidate", "Interviewer"}


def test_normalize_strips_participant_extra_data(raw_dir_scorecard: Path):
    fx = normalize(raw_dir_scorecard)
    for seg in fx.transcript.segments:
        assert "extra_data" not in seg["participant"]


def test_normalize_strips_signed_s3_url(raw_dir_scorecard: Path):
    fx = normalize(raw_dir_scorecard)
    payload = fx.model_dump()
    assert "signed.s3.aws.com" not in json.dumps(payload)


def test_normalize_computes_feedback_start_timestamp(raw_dir_scorecard: Path):
    fx = normalize(raw_dir_scorecard)
    # (07:21:57.951 - 06:06:24.005) ~ 4533.946 seconds
    assert fx.transcript.feedback_start_timestamp == pytest.approx(4533.946, abs=0.5)


def test_normalize_captures_baseline_outputs(raw_dir_scorecard: Path):
    fx = normalize(raw_dir_scorecard)
    assert fx.baseline_outputs.rating == "strong_yes"
    assert fx.baseline_outputs.summary == "She fell short..."
    assert fx.baseline_outputs.question_summaries == {"1": "..."}


def test_normalize_returns_fixture_instance(raw_dir_scorecard: Path):
    fx = normalize(raw_dir_scorecard)
    assert isinstance(fx, Fixture)


def test_normalize_handles_bot_path_no_scorecard(tmp_path: Path):
    """When scorecard_transcript is empty, source resolves to 'bot' if a bot is present."""
    _write(tmp_path, "step2_round.json", [{
        "candidate_round_id": "round-2",
        "candidate_name": "Sam Patel",
        "scorecard_transcript": "",
        "current_rating": "yes",
        "current_summary": "Solid.",
        "current_question_summaries": {},
        "current_competency_snapshots": "",
        "role_title": "Senior PM",
        "role_location": "Bangalore",
        "experience_min_years": 5,
        "experience_max_years": 8,
        "intake_notes": "",
        "job_description": "JD",
        "must_have_skills": [],
        "good_to_have_skills": [],
    }])
    _write(tmp_path, "step3_questions.json", [
        {"id": "q1", "question_number": 1, "heading": "H", "description": "D"},
    ])
    _write(tmp_path, "step4_transcript.json", [{
        "candidate_round_id": "round-2",
        "feedback_transcript": "real bot transcript",
        "segments": [],
        "raw_transcript_url": None,
    }])
    _write(tmp_path, "step5_bot.json", [{
        "feedback_started_at": "2026-05-12T01:00:00+00:00",
        "joined_at": "2026-05-12T00:00:00+00:00",
        "feedback_status": "partial",
    }])

    fx = normalize(tmp_path)
    assert fx.feedback_source.source == "bot"


def test_normalize_redacts_both_full_name_and_first_name(tmp_path: Path):
    """Mixed text with full name and first name: both redacted, no double-replacement."""
    _write(tmp_path, "step2_round.json", [{
        "candidate_round_id": "r",
        "candidate_name": "Lena Ortiz",
        "scorecard_transcript": "Met with Lena Ortiz today; Lena did well. M was helpful too.",
        "current_rating": None, "current_summary": None,
        "current_question_summaries": {}, "current_competency_snapshots": None,
        "role_title": "X", "role_location": "Y",
        "experience_min_years": 1, "experience_max_years": 2,
        "intake_notes": None, "job_description": "",
        "must_have_skills": [], "good_to_have_skills": [],
    }])
    _write(tmp_path, "step3_questions.json", [
        {"id": "q1", "question_number": 1, "heading": "H", "description": "D"},
    ])
    _write(tmp_path, "step4_transcript.json", [{
        "candidate_round_id": "r", "feedback_transcript": "",
        "segments": [], "raw_transcript_url": None,
    }])
    _write(tmp_path, "step5_bot.json", [{}])

    fx = normalize(tmp_path)
    text = fx.feedback_source.scorecard_transcript
    assert "Lena Ortiz" not in text  # full name redacted
    assert "Lena" not in text   # first name token also redacted
    # Single-letter "M" appearing as a separate token should NOT be redacted
    # (length-1 tokens skipped). It can appear in the result.
    assert "Candidate" in text


def test_normalize_redacts_candidate_name_in_words(tmp_path: Path):
    """Per-word transcribed text must be redacted just like derived transcripts."""
    _write(tmp_path, "step2_round.json", [{
        "candidate_round_id": "r",
        "candidate_name": "Lena Ortiz",
        "scorecard_transcript": "transcript",
        "current_rating": None, "current_summary": None,
        "current_question_summaries": {}, "current_competency_snapshots": None,
        "role_title": "X", "role_location": "Y",
        "experience_min_years": 1, "experience_max_years": 2,
        "intake_notes": None, "job_description": "",
        "must_have_skills": [], "good_to_have_skills": [],
    }])
    _write(tmp_path, "step3_questions.json", [
        {"id": "q1", "question_number": 1, "heading": "H", "description": "D"},
    ])
    _write(tmp_path, "step4_transcript.json", [{
        "candidate_round_id": "r", "feedback_transcript": "",
        "segments": [
            {"participant": {"id": 100, "name": "Lena"},
             "words": [{"text": "Hi"}, {"text": "Lena,"}, {"text": "how"}]},
            {"participant": {"id": 200, "name": "Priya"},
             "words": [{"text": "Yes."}, {"text": "Lena"}, {"text": "is"}, {"text": "great."}]},
        ],
        "raw_transcript_url": None,
    }])
    _write(tmp_path, "step5_bot.json", [{}])

    fx = normalize(tmp_path)
    for seg in fx.transcript.segments:
        for w in seg["words"]:
            assert "Lena" not in w["text"]


def test_normalize_whitelists_participant_fields(tmp_path: Path):
    """Participant dict is rebuilt from a whitelist — display_name/email/etc are dropped."""
    _write(tmp_path, "step2_round.json", [{
        "candidate_round_id": "r",
        "candidate_name": "Lena Ortiz",
        "scorecard_transcript": "x",
        "current_rating": None, "current_summary": None,
        "current_question_summaries": {}, "current_competency_snapshots": None,
        "role_title": "X", "role_location": "Y",
        "experience_min_years": 1, "experience_max_years": 2,
        "intake_notes": None, "job_description": "",
        "must_have_skills": [], "good_to_have_skills": [],
    }])
    _write(tmp_path, "step3_questions.json", [
        {"id": "q1", "question_number": 1, "heading": "H", "description": "D"},
    ])
    _write(tmp_path, "step4_transcript.json", [{
        "candidate_round_id": "r", "feedback_transcript": "",
        "segments": [
            {"participant": {
                "id": 100, "name": "Lena", "display_name": "Lena Ortiz",
                "email": "keerthi@example.com", "is_host": True,
                "extra_data": {"teams": "should-be-stripped"},
                "platform_user_id": "should-be-stripped-too",
            }, "words": [{"text": "Hi"}]},
        ],
        "raw_transcript_url": None,
    }])
    _write(tmp_path, "step5_bot.json", [{}])

    fx = normalize(tmp_path)
    p = fx.transcript.segments[0]["participant"]
    assert set(p.keys()) == {"id", "name"}  # whitelist
    assert p["name"] == "Candidate"
