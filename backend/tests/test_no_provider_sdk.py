"""No provider SDK reaches this backend. Phase 3's end state, pinned.

Replaces test_anthropic_surface.py, which existed to fail until the streaming
path migrated. Every property it guarded is here; the two that carried an
allowlist of surviving Anthropic consumers now assert the empty set, and two are
new — that the SDK is gone from requirements.txt, not merely unimported, and
that intake-core no longer pins it transitively.

These are SOURCE-TEXT assertions, not import checks, on purpose: a regression
here is someone TYPING the old shape back into a module, and that has to fail in
this suite rather than at runtime against a provider.

Deliberately NOT asserted: that the string "anthropic" is absent from
backend/app. candidate_detection_service.py and recall_webhook/end_state.py POST
raw httpx to api.anthropic.com and read settings.ANTHROPIC_API_KEY. They import
no SDK, they belong to no phase in the current rollout, and they are out of
scope — see the spec's six-surface inventory, which does not list them.
"""

from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_APP = _BACKEND / "app"
_REPO = _BACKEND.parent


def _modules_containing(needle: str) -> set[str]:
    return {
        path.relative_to(_APP).as_posix()
        for path in _APP.rglob("*.py")
        if needle in path.read_text(encoding="utf-8")
    }


def test_no_module_imports_the_anthropic_sdk():
    assert _modules_containing("from anthropic import") == set()
    assert _modules_containing("import anthropic") == set()


def test_the_anthropic_client_factory_is_gone():
    assert _modules_containing("get_anthropic_async_client") == set()


def test_the_anthropic_pin_is_gone_from_requirements():
    """Unimported is not uninstalled. The pin's removal is what makes the image
    stop shipping the SDK, and it is the half of the deletion a source grep over
    app/ cannot see."""
    requirements = (_BACKEND / "requirements.txt").read_text(encoding="utf-8")
    assert "anthropic" not in requirements


def test_intake_core_does_not_pin_the_sdk_transitively():
    """The other half, and the one that nearly shipped.

    intake-core is installed INTO the backend image, so its own
    `anthropic>=0.40,<1.0` kept the SDK importable no matter what
    backend/requirements.txt said — and no source scan over backend/app could
    see it. Skipped rather than failed when the checkout is not present, because
    `make test` mounts only backend/ and the repo root is not always reachable.
    """
    pyproject = _REPO / "intake-core" / "pyproject.toml"
    if not pyproject.exists():
        return
    body = pyproject.read_text(encoding="utf-8")
    dependency_lines = [
        line for line in body.splitlines() if "anthropic" in line and "#" not in line
    ]
    assert dependency_lines == []


def test_no_module_speaks_the_anthropic_messages_api():
    """Both halves: .messages.create was the non-streaming call, .messages.stream
    the streaming one. Phase 2 removed the first; phase 3 removed the second."""
    assert _modules_containing(".messages.create(") == set()
    assert _modules_containing(".messages.stream(") == set()


def test_no_module_carries_an_anthropic_tool_spec():
    """llm_core rejects `input_schema` rather than translating it, on the native
    path as well as the emulated one — but at CALL time, and several call sites
    sit behind seams their own tests mock. Failing here means it cannot reach a
    running system."""
    assert _modules_containing("input_schema") == set()


def test_no_module_passes_an_anthropic_shaped_tool_choice():
    assert _modules_containing('{"type": "tool", "name"') == set()


def test_no_module_reads_a_tool_call_positionally():
    """Forcing guarantees the named tool IS called — not that it is the ONLY call.
    Measured against anthropic/claude-sonnet-5 through the live gateway: a forced
    request returned [forced_tool, second_tool]. Every site therefore reads via
    LLMReply.tool_call_named or by matching the streamed event's `name`."""
    assert _modules_containing("tool_calls[") == set()
