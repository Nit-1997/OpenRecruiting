"""Tests for the screening module: snapshot, dynamic prompt builder, persona seam, tool handler."""

from intake_core.screening.builder import build_screening_prompt
from intake_core.screening.questions import snapshot_questions
from intake_core.screening.persona import SCREENING_GUARDRAILS
from intake_core.screening.tools import (
    ALL_SCREENING_TOOLS,
    handle_mark_question_covered,
)


def test_prompt_renders_questions_and_guardrails():
    qs = snapshot_questions([{"id": "q1", "prompt": "Walk me through a metric you owned",
                              "signal": "EXECUTION", "probe": "causal or correlated?"}])
    prompt = build_screening_prompt({"questions": qs, "role_context": "PM role", "answered": []})
    assert "Walk me through a metric you owned" in prompt
    assert "probe: causal or correlated?" in prompt
    assert "NON-NEGOTIABLE RULES" in prompt


def test_answered_question_marked_done():
    qs = snapshot_questions([{"id": "q1", "prompt": "Q1"}])
    prompt = build_screening_prompt({"questions": qs, "answered": ["q1"]})
    assert "[done]" in prompt


def test_persona_snapshot_overrides_generic():
    qs = snapshot_questions([{"id": "q1", "prompt": "Q1"}])
    prompt = build_screening_prompt({"questions": qs, "answered": [],
                                     "persona_snapshot": {"text": "CUSTOM PERSONA XYZ"}})
    assert "CUSTOM PERSONA XYZ" in prompt
    assert "NON-NEGOTIABLE RULES" in prompt  # guardrails still present


def test_persona_snapshot_without_text_falls_back_to_generic():
    qs = snapshot_questions([{"id": "q1", "prompt": "Q1"}])
    # Phase-2 seam: an empty/absent text key must fall back to the generic persona.
    prompt = build_screening_prompt({"questions": qs, "answered": [],
                                     "persona_snapshot": {}})
    assert "You are Scout" in prompt


def test_snapshot_orders_and_reindexes():
    qs = snapshot_questions([
        {"id": "b", "prompt": "second", "order_index": 5},
        {"id": "a", "prompt": "first", "order_index": 2},
    ])
    assert [q["id"] for q in qs] == ["a", "b"]
    assert [q["order_index"] for q in qs] == [0, 1]


def test_snapshot_defaults_and_jsonable():
    import json
    qs = snapshot_questions([{"id": 1, "prompt": "Q"}])
    json.dumps(qs)  # must serialize
    q = qs[0]
    assert q["id"] == "1"  # coerced to str
    assert q["probe"] == ""
    assert q["signal"] == ""
    assert q["dimension"] == ""
    assert q["duration_minutes"] == 5
    assert q["title"] == ""


def test_handle_mark_question_covered_adds_id():
    state = {}
    result = handle_mark_question_covered(state, "q1")
    assert result["ok"] is True
    assert "q1" in result["answered"]
    assert "q1" in state["answered"]


def test_handle_mark_question_covered_idempotent():
    state = {"answered": ["q1"]}
    handle_mark_question_covered(state, "q1")
    handle_mark_question_covered(state, "q1")
    assert state["answered"].count("q1") == 1


def test_all_screening_tools_shape():
    assert isinstance(ALL_SCREENING_TOOLS, list)
    assert len(ALL_SCREENING_TOOLS) == 1
    tool = ALL_SCREENING_TOOLS[0]
    assert tool["type"] == "function"
    fn = tool["function"]
    assert fn["name"] == "mark_question_covered"
    assert "description" in fn and len(fn["description"]) > 20
    schema = fn["parameters"]
    assert schema["type"] == "object"
    assert "question_id" in schema["properties"]
    assert "question_id" in schema["required"]
