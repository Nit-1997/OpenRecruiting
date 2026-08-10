"""Phase 2 leaves the Anthropic SDK alive on purpose.

get_anthropic_async_client still feeds the two STREAMING entry points, which
phase 3 owns: anthropic_stream.py -> llm_stream.py, plus the rewrites of
text_runner.py and debrief_chat/runner.py. Both build Anthropic-shaped REQUEST
history, so neither can be wrapped — see the hazards section of
docs/superpowers/plans/2026-08-07-llm-gateway-foundation.md. Dropping the
`anthropic` pin from requirements.txt now would break them at import.

This file pins what is left so the nine call sites phase 2 migrated cannot
silently regrow. Phase 3 empties _EXPECTED_CLIENT_USERS, deletes the factory,
drops the pin, and deletes this file.

These are source-text assertions, not import checks, on purpose: a regression
here is someone TYPING the old shape back into a module, and that has to fail in
the suite rather than at runtime against a provider.
"""

from pathlib import Path

_APP = Path(__file__).resolve().parent.parent / "app"

# Streaming only. Anything else appearing here is a phase-2 regression.
_EXPECTED_CLIENT_USERS = {
    "api/v2/routers/debrief_chat.py",
    "api/v2/routers/intake_text_messages.py",
}

# Phase 3's, and the only module still allowed to carry Anthropic tool specs.
_STREAMING_TOOL_SPECS = "services/debrief_chat/tool_specs.py"


def _modules_containing(needle: str) -> set[str]:
    return {
        path.relative_to(_APP).as_posix()
        for path in _APP.rglob("*.py")
        if needle in path.read_text(encoding="utf-8")
    }


def test_only_the_streaming_routers_still_take_the_anthropic_client():
    users = _modules_containing("get_anthropic_async_client") - {"dependencies.py"}
    assert users == _EXPECTED_CLIENT_USERS


def test_the_anthropic_sdk_is_imported_in_exactly_one_place():
    assert _modules_containing("from anthropic import") == {"dependencies.py"}


def test_no_migrated_module_still_speaks_the_anthropic_message_api():
    """messages.create is the Anthropic non-streaming call. Every one of the nine
    is gone; messages.stream (the phase-3 wrapper) is deliberately not matched."""
    assert _modules_containing(".messages.create(") == set()


def test_only_the_streaming_tool_specs_still_use_input_schema():
    """The eight migrated specs carry `parameters` inside an OpenAI `function`
    envelope. llm_core rejects `input_schema` outright, so a straggler would fail
    loudly — but only on the code path that runs, and this catches it statically."""
    assert _modules_containing("input_schema") == {_STREAMING_TOOL_SPECS}


def test_no_module_reads_a_tool_call_positionally():
    """Forcing guarantees the named tool IS called — not that it is the ONLY call.

    Measured against anthropic/claude-sonnet-5 through the live gateway: a forced
    request returned [forced_tool, second_tool]. Every migrated site therefore
    reads via LLMReply.tool_call_named, which is name-matched and unaffected. A
    positional read would silently pick the wrong tool's arguments the first time
    a model volunteers an extra call, and eight of the nine sites parse those
    arguments into something a recruiter sees.
    """
    assert _modules_containing("tool_calls[") == set()


def test_no_module_passes_an_anthropic_shaped_tool_choice():
    """The migration mistake this phase was most likely to leave behind.

    Six sites carried Anthropic's {"type": "tool", "name": ...} before migrating.
    llm_core's validate_tool_choice rejects that shape with a message naming the
    conversion, so a straggler raises LLMError rather than degrading — but it
    raises at call time, and several of these sites are behind seams their tests
    mock. Failing here instead means it cannot reach a running system.
    """
    assert _modules_containing('{"type": "tool", "name"') == set()
