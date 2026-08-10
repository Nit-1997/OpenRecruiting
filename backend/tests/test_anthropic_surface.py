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

# Shrinks as phase 3 migrates each streaming router. Anything appearing here that
# is not listed is a regression; anything listed that has already migrated should
# be REMOVED in the same commit that migrates it, so the suite stays green after
# every task rather than sitting red until the final deletion.
#
# debrief_chat.py left this set in Task 3. intake_text_messages.py leaves it in
# Task 4, at which point the set is empty and Task 6 deletes this whole file
# along with the factory and the pin.
_EXPECTED_CLIENT_USERS = {
    "api/v2/routers/intake_text_messages.py",
}

# Modules in backend/app still carrying Anthropic-shaped tool specs. Task 3
# converted debrief_chat/tool_specs.py, which was the last one — intake-core's
# schemas.py still has an Anthropic export for the voice agent, but it lives
# outside backend/app and is deliberately retained until phase 7.
_ANTHROPIC_TOOL_SPEC_MODULES: set[str] = set()


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


def test_no_module_in_the_app_still_uses_input_schema():
    """All nineteen migrated specs — phase 2's eight, plus phase 3's eleven debrief
    tools — carry `parameters` inside an OpenAI `function` envelope. llm_core
    rejects `input_schema` outright, so a straggler would fail loudly, but only on
    the code path that runs; this catches it statically."""
    assert _modules_containing("input_schema") == _ANTHROPIC_TOOL_SPEC_MODULES


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
