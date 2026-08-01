"""Test the 9 intake questions definition and snapshot helper."""

from intake_core.questions import INTAKE_QUESTIONS, QUESTIONS_VERSION, snapshot_questions


def test_nine_questions_defined():
    assert len(INTAKE_QUESTIONS) == 9


def test_questions_have_required_fields():
    for q in INTAKE_QUESTIONS:
        assert q["id"].startswith("q")
        assert isinstance(q["topic"], str) and q["topic"]
        assert isinstance(q["default_text"], str) and q["default_text"]
        assert q["order"] in range(1, 10)


def test_question_ids_unique():
    ids = [q["id"] for q in INTAKE_QUESTIONS]
    assert len(ids) == len(set(ids))


def test_questions_version_format():
    assert QUESTIONS_VERSION.startswith("v1-")
    assert len(QUESTIONS_VERSION) >= 13  # v1-YYYY-MM-DD


def test_snapshot_returns_jsonable_copy():
    import json
    snap = snapshot_questions()
    json.dumps(snap)  # must serialize
    assert len(snap) == 9
    # snapshot mutation must not affect the source
    snap[0]["topic"] = "MUTATED"
    assert INTAKE_QUESTIONS[0]["topic"] != "MUTATED"
