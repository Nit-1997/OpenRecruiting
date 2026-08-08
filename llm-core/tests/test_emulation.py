import pytest

from llm_core.emulation import build_emulation_instruction, parse_emulated_reply
from llm_core.errors import ToolEmulationError

TOOL = {
    "type": "function",
    "function": {
        "name": "emit_job_description",
        "description": "Return the structured job description.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["title"],
        },
    },
}

# The shape every tool spec in this repo actually uses today (jd_parser.py,
# debrief_chat/tool_specs.py, intake_core/tools/schemas.py). It must be rejected
# loudly, not silently misread as a tool literally named "tool" with no schema.
ANTHROPIC_TOOL = {
    "name": "emit_job_description",
    "description": "Return the structured job description.",
    "input_schema": {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    },
}

SECOND_TOOL = {
    "type": "function",
    "function": {
        "name": "get_transcript_evidence",
        "description": "Return interview transcript excerpts for a candidate.",
        "parameters": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string"},
                "topic": {"type": "string"},
            },
            "required": ["candidate_id", "topic"],
        },
    },
}


def test_instruction_names_the_tool_and_embeds_the_schema():
    text = build_emulation_instruction([TOOL])

    assert "emit_job_description" in text
    assert '"title"' in text
    assert "JSON" in text


def test_parses_plain_json_object():
    call = parse_emulated_reply('{"title": "SRE", "location": "Remote"}', [TOOL])

    assert call.name == "emit_job_description"
    assert call.arguments == {"title": "SRE", "location": "Remote"}
    assert call.id.startswith("emulated-")


def test_parses_json_wrapped_in_a_fenced_code_block():
    raw = 'Sure!\n```json\n{"title": "SRE"}\n```\n'

    call = parse_emulated_reply(raw, [TOOL])

    assert call.arguments == {"title": "SRE"}


def test_accepts_tool_name_envelope():
    raw = '{"name": "emit_job_description", "arguments": {"title": "SRE"}}'

    call = parse_emulated_reply(raw, [TOOL])

    assert call.arguments == {"title": "SRE"}


def test_rejects_missing_required_property():
    with pytest.raises(ToolEmulationError) as exc:
        parse_emulated_reply('{"location": "Remote"}', [TOOL])

    assert "title" in str(exc.value)


def test_rejects_unparseable_output():
    with pytest.raises(ToolEmulationError):
        parse_emulated_reply("I cannot help with that.", [TOOL])


def test_build_rejects_anthropic_shaped_tool():
    with pytest.raises(ToolEmulationError) as exc:
        build_emulation_instruction([ANTHROPIC_TOOL])

    message = str(exc.value)
    assert "emit_job_description" in message
    assert "input_schema" in message


def test_parse_rejects_anthropic_shaped_tool():
    with pytest.raises(ToolEmulationError) as exc:
        parse_emulated_reply('{"title": "SRE"}', [ANTHROPIC_TOOL])

    message = str(exc.value)
    assert "emit_job_description" in message
    assert "input_schema" in message


def test_build_rejects_empty_tool_list():
    with pytest.raises(ToolEmulationError):
        build_emulation_instruction([])


def test_parse_rejects_empty_tool_list():
    # Reachable: text_runner.py passes tools=[] on the greeting turn. Must stay
    # inside the LLMError hierarchy, not surface as IndexError.
    with pytest.raises(ToolEmulationError):
        parse_emulated_reply('{"title": "SRE"}', [])


def test_multi_tool_instruction_describes_every_tool_and_demands_the_envelope():
    text = build_emulation_instruction([TOOL, SECOND_TOOL])

    assert "emit_job_description" in text
    assert "get_transcript_evidence" in text
    assert '"candidate_id"' in text
    assert '"title"' in text
    assert '"arguments"' in text


def test_multi_tool_envelope_selects_the_named_tool():
    raw = '{"name": "get_transcript_evidence", "arguments": {"candidate_id": "c1", "topic": "sql"}}'

    call = parse_emulated_reply(raw, [TOOL, SECOND_TOOL])

    assert call.name == "get_transcript_evidence"
    assert call.arguments == {"candidate_id": "c1", "topic": "sql"}


def test_multi_tool_validates_against_the_named_tools_schema():
    # Satisfies TOOL's schema but not the tool it actually named.
    raw = '{"name": "get_transcript_evidence", "arguments": {"title": "SRE"}}'

    with pytest.raises(ToolEmulationError) as exc:
        parse_emulated_reply(raw, [TOOL, SECOND_TOOL])

    assert "candidate_id" in str(exc.value)


def test_multi_tool_rejects_unknown_tool_name():
    raw = '{"name": "delete_everything", "arguments": {"title": "SRE"}}'

    with pytest.raises(ToolEmulationError) as exc:
        parse_emulated_reply(raw, [TOOL, SECOND_TOOL])

    message = str(exc.value)
    assert "delete_everything" in message
    assert "emit_job_description" in message
    assert "get_transcript_evidence" in message


def test_multi_tool_refuses_to_guess_when_reply_names_no_tool():
    with pytest.raises(ToolEmulationError):
        parse_emulated_reply('{"title": "SRE"}', [TOOL, SECOND_TOOL])


def test_missing_property_error_reports_the_keys_that_did_arrive():
    with pytest.raises(ToolEmulationError) as exc:
        parse_emulated_reply('{"locaiton": "Remote", "summry": "x"}', [TOOL])

    message = str(exc.value)
    assert "title" in message
    assert "locaiton" in message
    assert "summry" in message


def test_non_object_error_carries_a_snippet_of_the_offending_output():
    with pytest.raises(ToolEmulationError) as exc:
        parse_emulated_reply('["title", "SRE"]', [TOOL])

    message = str(exc.value)
    assert "list" in message
    assert "SRE" in message
