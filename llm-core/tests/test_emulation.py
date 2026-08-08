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
