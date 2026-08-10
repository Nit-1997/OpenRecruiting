"""Validate tool schemas conform to Anthropic tool-use shape."""

from intake_core.tools.schemas import UPDATE_ANSWER_TOOL, MARK_STATUS_TOOL, ALL_TOOLS


def test_update_answer_tool_shape():
    t = UPDATE_ANSWER_TOOL
    assert t["name"] == "update_answer"
    assert "description" in t and len(t["description"]) > 20
    schema = t["input_schema"]
    assert schema["type"] == "object"
    props = schema["properties"]
    assert set(props.keys()) >= {"qid", "text", "confidence"}
    assert "qid" in schema["required"]
    assert "text" in schema["required"]
    assert "confidence" in schema["required"]
    assert set(props["confidence"]["enum"]) == {"none", "low", "medium", "high"}


def test_mark_status_tool_shape():
    t = MARK_STATUS_TOOL
    assert t["name"] == "mark_status"
    schema = t["input_schema"]
    assert set(schema["properties"]["status"]["enum"]) == {
        "untouched", "needs_probe", "discussed", "validated", "skipped"
    }
    assert "qid" in schema["required"]
    assert "status" in schema["required"]


def test_all_tools_is_list_of_two():
    assert isinstance(ALL_TOOLS, list)
    assert len(ALL_TOOLS) == 2
    names = {t["name"] for t in ALL_TOOLS}
    assert names == {"update_answer", "mark_status"}


def test_qid_enum_lists_nine_questions():
    """qid parameter should be constrained to the 9 known question IDs."""
    expected = {
        "q1_role_overview", "q2_rounds", "q3_focus_areas", "q4_must_haves",
        "q5_nice_to_haves", "q6_cultural_fit", "q7_team_structure",
        "q8_red_flags", "q9_anything_else",
    }
    for tool in [UPDATE_ANSWER_TOOL, MARK_STATUS_TOOL]:
        assert set(tool["input_schema"]["properties"]["qid"]["enum"]) == expected


from intake_core.tools.schemas import ALL_TOOLS_OPENAI  # noqa: E402


def test_openai_export_mirrors_every_anthropic_spec():
    assert len(ALL_TOOLS_OPENAI) == len(ALL_TOOLS)
    for old, new in zip(ALL_TOOLS, ALL_TOOLS_OPENAI):
        assert set(new) == {"type", "function"}
        assert new["type"] == "function"
        assert set(new["function"]) == {"name", "description", "parameters"}
        assert new["function"]["name"] == old["name"]
        assert new["function"]["description"] is old["description"]
        assert new["function"]["parameters"] is old["input_schema"]


def test_openai_export_carries_the_computed_qid_enum():
    """The enum is computed from INTAKE_QUESTIONS, which is why these specs are
    not literal_eval-able and why the derivation shares the object rather than
    copying it."""
    for tool in ALL_TOOLS_OPENAI:
        enum = tool["function"]["parameters"]["properties"]["qid"]["enum"]
        assert len(enum) == 9
        assert "q4_must_haves" in enum


def test_the_anthropic_export_is_untouched_for_the_voice_agent():
    """voice-agent/src/main.py:43 still imports ALL_TOOLS and hands it to
    pipecat's AnthropicLLMService. Phase 7 moves it; until then this shape is
    load-bearing and no voice-agent test would catch its removal."""
    for tool in ALL_TOOLS:
        assert set(tool) == {"name", "description", "input_schema"}
