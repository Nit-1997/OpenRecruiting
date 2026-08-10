"""The intake tool specs, in the shape the gateway accepts.

text_runner hands these to llm_core.stream_turn, which REJECTS Anthropic-shaped
specs rather than translating them (llm_core/emulation.py:84-93). This is the
backend-side guard for that; intake-core's own suite (not run by `make test`)
covers the derivation itself.
"""
from llm_core.emulation import validate_tool_shape

from intake_core.tools import INTAKE_TOOLS_ANTHROPIC, INTAKE_TOOLS_OPENAI


def test_the_openai_export_is_accepted_by_llm_core():
    entries = validate_tool_shape(INTAKE_TOOLS_OPENAI)
    assert [name for name, _description, _schema in entries] == [
        "update_answer",
        "mark_status",
    ]


def test_the_two_exports_describe_the_same_two_tools():
    """Proof the specs were MOVED, not retyped: `parameters` is the SAME OBJECT
    as the source `input_schema`, which no retype can satisfy. A diff cannot show
    this, because reindentation touches every line."""
    assert len(INTAKE_TOOLS_OPENAI) == len(INTAKE_TOOLS_ANTHROPIC) == 2
    for old, new in zip(INTAKE_TOOLS_ANTHROPIC, INTAKE_TOOLS_OPENAI):
        assert new["type"] == "function"
        assert new["function"]["name"] == old["name"]
        assert new["function"]["description"] is old["description"]
        assert new["function"]["parameters"] is old["input_schema"]
