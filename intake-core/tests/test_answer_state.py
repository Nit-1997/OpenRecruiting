"""Test per-answer state types and transitions."""

import pytest
from intake_core.state.answer_state import (
    AnswerStatus,
    Confidence,
    AnswerState,
    new_untouched,
    apply_user_input,
)


def test_answer_status_values():
    assert AnswerStatus.UNTOUCHED.value == "untouched"
    assert AnswerStatus.NEEDS_PROBE.value == "needs_probe"
    assert AnswerStatus.DISCUSSED.value == "discussed"
    assert AnswerStatus.VALIDATED.value == "validated"
    assert AnswerStatus.SKIPPED.value == "skipped"


def test_new_untouched_with_prefill():
    s = new_untouched(prefilled_text="Python, PG", confidence=Confidence.MEDIUM, sources=["jd"])
    assert s.status == AnswerStatus.UNTOUCHED
    assert s.text == "Python, PG"  # initialized from prefill
    assert s.prefilled_text == "Python, PG"
    assert s.extraction_confidence == Confidence.MEDIUM
    assert s.sources == ["jd"]
    assert s.turns_addressed == []


def test_new_untouched_without_prefill():
    s = new_untouched()
    assert s.status == AnswerStatus.UNTOUCHED
    assert s.text is None
    assert s.prefilled_text is None
    assert s.extraction_confidence == Confidence.NONE
    assert s.sources == []


def test_apply_user_input_advances_state():
    s = new_untouched()
    s2 = apply_user_input(s, text="We do 4 rounds", confidence=Confidence.HIGH, turn_idx=5)
    assert s2.status == AnswerStatus.DISCUSSED
    assert s2.text == "We do 4 rounds"
    assert s2.extraction_confidence == Confidence.HIGH
    assert 5 in s2.turns_addressed


def test_apply_user_input_appends_to_existing():
    s = new_untouched(prefilled_text="Python", confidence=Confidence.LOW, sources=["jd"])
    s2 = apply_user_input(s, text="Python, also Kafka", confidence=Confidence.HIGH, turn_idx=3)
    assert s2.text == "Python, also Kafka"
    assert s2.status == AnswerStatus.DISCUSSED
    assert s2.extraction_confidence == Confidence.HIGH
    assert s2.turns_addressed == [3]


def test_answer_state_serializable():
    import json
    s = new_untouched(prefilled_text="x", confidence=Confidence.LOW, sources=["jd"])
    json.dumps(s.to_dict())


def test_answer_state_round_trip():
    s = new_untouched(prefilled_text="x", confidence=Confidence.LOW, sources=["jd"])
    s.turns_addressed = [1, 2]
    s.status = AnswerStatus.VALIDATED
    d = s.to_dict()
    s2 = AnswerState.from_dict(d)
    assert s2.status == AnswerStatus.VALIDATED
    assert s2.turns_addressed == [1, 2]
    assert s2.text == "x"
