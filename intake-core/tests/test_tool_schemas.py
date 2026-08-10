"""Validate tool schemas conform to the OpenAI function shape.

One shape only. The dual export phase 3 shipped (Anthropic `ALL_TOOLS` plus a
derived `ALL_TOOLS_OPENAI`) is gone, so phase 3's sentinel
`test_the_anthropic_export_is_untouched_for_the_voice_agent` is RETIRED rather
than deleted quietly: it existed to stop the Anthropic export vanishing while
voice-agent still consumed it, and phase 4 removes it on purpose. Its actual job
— nobody may silently change what voice-agent consumes — now lives in
voice-agent/tests/pipeline/test_tool_schemas.py, which tests the real reader.

What survives here is the invariant that outlives the shape change: every spec
carries the `required` list that both degraded-reply guards are keyed on
(backend text_runner._missing_args and debrief runner._missing_args).
"""

from intake_core.tools.schemas import (
    UPDATE_ANSWER_TOOL,
    MARK_STATUS_TOOL,
    ALL_TOOLS_OPENAI,
)


def _fn(spec):
    return spec["function"]


def test_update_answer_tool_shape():
    t = UPDATE_ANSWER_TOOL
    assert t["type"] == "function"
    assert _fn(t)["name"] == "update_answer"
    schema = _fn(t)["parameters"]
    assert schema["type"] == "object"
    assert "qid" in schema["properties"]
    assert "text" in schema["properties"]
    assert "confidence" in schema["properties"]


def test_mark_status_tool_shape():
    t = MARK_STATUS_TOOL
    assert t["type"] == "function"
    assert _fn(t)["name"] == "mark_status"
    schema = _fn(t)["parameters"]
    assert set(schema["required"]) == {"qid", "status"}


def test_qid_enum_covers_every_intake_question():
    from intake_core.questions import INTAKE_QUESTIONS

    enum = _fn(UPDATE_ANSWER_TOOL)["parameters"]["properties"]["qid"]["enum"]
    assert enum == [q["id"] for q in INTAKE_QUESTIONS]
    assert len(enum) == 9


def test_all_tools_is_the_only_export_and_is_openai_shaped():
    assert isinstance(ALL_TOOLS_OPENAI, list)
    assert len(ALL_TOOLS_OPENAI) == 2
    for spec in ALL_TOOLS_OPENAI:
        assert set(spec) == {"type", "function"}
        assert spec["type"] == "function"
        assert set(_fn(spec)) == {"name", "description", "parameters"}


def test_every_spec_declares_the_required_list_the_guards_key_on():
    """Both degraded-reply guards derive their expectations from this list. A
    spec without one would make a truncated call indistinguishable from a real
    one at that call site."""
    for spec in ALL_TOOLS_OPENAI:
        required = _fn(spec)["parameters"].get("required")
        assert required, _fn(spec)["name"]
        properties = _fn(spec)["parameters"]["properties"]
        for name in required:
            assert name in properties, f"{_fn(spec)['name']}.{name}"


def test_no_anthropic_shape_survives():
    """The flip must be total: a leftover input_schema anywhere would be accepted
    by nothing (llm_core rejects it, voice-agent's reader refuses it)."""
    for spec in ALL_TOOLS_OPENAI:
        assert "input_schema" not in spec
        assert "input_schema" not in _fn(spec)
