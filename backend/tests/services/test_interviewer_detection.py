"""Characterization tests for the no-LLM interviewer email detector."""

from app.services.recall_webhook.interviewer_detection import (
    detect_interviewer_emails,
    is_interviewer,
)


def test_is_interviewer_host_or_tenant():
    assert is_interviewer({"is_host": True}) is True
    assert is_interviewer({"is_tenant": True}) is True
    assert is_interviewer({"is_host": False, "is_tenant": False}) is False
    assert is_interviewer({}) is False


def test_empty_participants_returns_empty():
    assert detect_interviewer_emails([], "Alice") == []


def test_host_flag_wins_and_dedupes_sorted():
    participants = [
        {"is_host": True, "email": "b@m.ai"},
        {"is_tenant": True, "email": "a@m.ai"},
        {"is_host": True, "email": "a@m.ai"},  # dup
        {"email": "candidate@m.ai"},  # not flagged, ignored
    ]
    assert detect_interviewer_emails(participants, "Alice") == ["a@m.ai", "b@m.ai"]


def test_flagged_without_email_skipped():
    participants = [{"is_host": True}, {"email": "x@m.ai"}]
    # host has no email -> falls through to name-exclusion path; candidate "Bob"
    # doesn't match any participant name -> ambiguous
    assert detect_interviewer_emails(participants, "Bob") == []


def test_single_non_candidate_with_email():
    participants = [
        {"name": "Alice Cand", "email": "alice@m.ai"},
        {"name": "Bob Interviewer", "email": "bob@m.ai"},
    ]
    assert detect_interviewer_emails(participants, "Alice Cand") == ["bob@m.ai"]


def test_blank_candidate_name_returns_empty():
    participants = [{"name": "Bob", "email": "bob@m.ai"}]
    assert detect_interviewer_emails(participants, "   ") == []


def test_candidate_name_no_match_is_ambiguous():
    participants = [{"name": "Bob", "email": "bob@m.ai"}]
    assert detect_interviewer_emails(participants, "Zoe Nothere") == []


def test_multiple_non_candidates_is_ambiguous():
    participants = [
        {"name": "Alice Cand", "email": "alice@m.ai"},
        {"name": "Bob One", "email": "bob@m.ai"},
        {"name": "Carol Two", "email": "carol@m.ai"},
    ]
    assert detect_interviewer_emails(participants, "Alice Cand") == []


def test_participant_without_name_skipped():
    participants = [
        {"name": "Alice Cand", "email": "alice@m.ai"},
        {"name": "", "email": "ghost@m.ai"},
        {"name": "Bob Solo", "email": "bob@m.ai"},
    ]
    assert detect_interviewer_emails(participants, "Alice Cand") == ["bob@m.ai"]
