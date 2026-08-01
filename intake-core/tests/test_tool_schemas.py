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
