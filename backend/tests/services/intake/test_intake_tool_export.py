"""The intake tool specs, in the shape the gateway accepts.

text_runner hands these to llm_core.stream_turn, which REJECTS Anthropic-shaped
specs rather than translating them (llm_core/emulation.py). This is the
backend-side guard for that.

Phase 3's `test_the_two_exports_describe_the_same_two_tools` is REPLACED, not
deleted: it proved the derived OpenAI export shared objects with the Anthropic
one, and phase 4 removed the Anthropic one, so there is no second object left to
be identical to. What replaces it is the property that still matters here — the
single exported shape is accepted by the very function llm_core runs before
dispatch, and it carries the `required` list text_runner's degraded-reply guard
is keyed on.
"""
from llm_core.emulation import validate_tool_shape

from intake_core.tools import INTAKE_TOOLS


def test_the_export_is_accepted_by_llm_core():
    entries = validate_tool_shape(INTAKE_TOOLS)
    assert [name for name, _description, _schema in entries] == [
        "update_answer",
        "mark_status",
    ]


def test_there_is_only_one_exported_shape():
    """A leftover Anthropic export would be an invitation to send it somewhere.
    llm_core rejects `input_schema` at call time; this fails at import time."""
    import intake_core.tools as tools

    assert not hasattr(tools, "INTAKE_TOOLS_ANTHROPIC")
    assert not hasattr(tools, "INTAKE_TOOLS_OPENAI")
    for spec in INTAKE_TOOLS:
        assert set(spec) == {"type", "function"}
        assert "input_schema" not in spec["function"]


def test_every_spec_carries_the_required_list_the_guard_needs():
    """text_runner._missing_args derives its expectations from this. A spec
    without a `required` list makes a truncated call indistinguishable from a
    real one at that call site."""
    for spec in INTAKE_TOOLS:
        assert spec["function"]["parameters"].get("required")
