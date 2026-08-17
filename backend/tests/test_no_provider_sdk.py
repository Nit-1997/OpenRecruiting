"""No provider SDK reaches this backend. Phase 3's end state, pinned.

Replaces test_anthropic_surface.py, which existed to fail until the streaming
path migrated. Every property it guarded is here; the two that carried an
allowlist of surviving Anthropic consumers now assert the empty set, and two are
new — that the SDK is gone from requirements.txt, not merely unimported, and
that intake-core no longer pins it transitively.

These are SOURCE-TEXT assertions, not import checks, on purpose: a regression
here is someone TYPING the old shape back into a module, and that has to fail in
this suite rather than at runtime against a provider.

Phase 8 closed the last hole this file used to document as out of scope:
candidate_detection_service.py and recall_webhook/end_state.py POSTed raw httpx
straight to the provider. They imported no SDK, so every assertion here
passed while the backend was still egressing to a provider directly — which is
exactly why `test_no_module_posts_to_a_provider_endpoint` now exists. No phase in
the spec's rollout covered them; phase 1 had created their aliases and nothing
ever used them.

Phase 7 finished the migration and added the one assertion that is not about
this backend: `test_no_application_module_holds_a_provider_credential` scans
EVERY service's source tree. Everything above it scans backend/app alone, and a
per-service scan structurally cannot see a repo-wide property — which is how
voice-agent held the last provider credential in the repository while every
suite here stayed green.
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


def test_no_module_posts_to_a_provider_endpoint():
    """The hole an SDK-import scan cannot see.

    Two services reached the provider over raw httpx until phase 8, holding an
    API key in a header. Nothing above would have caught it: they imported no
    SDK, used no Anthropic tool shape, and named no provider model class. The
    spec's goal is that ANTHROPIC_API_KEY is consumed only by the proxy, and this
    is the assertion that actually enforces it.
    """
    assert _modules_containing("api.anthropic.com") == set()
    assert _modules_containing("api.openai.com") == set()


def test_no_module_sends_a_provider_auth_header():
    """The other half: an endpoint can be reached via a variable, but the auth
    scheme gives it away. The gateway takes `Authorization: Bearer`, never these."""
    assert _modules_containing('"x-api-key"') == set()
    assert _modules_containing("anthropic-version") == set()


# The OTHER services' source trees (backend/app is scanned via _APP, which is the
# live mount rather than a baked copy). `workers/*/src` is a glob so a new worker
# is covered the day it is added, not the day someone remembers this file.
_OTHER_SERVICE_TREES = (
    "voice-agent/src",
    "intake-core/intake_core",
    "llm-core/llm_core",
    "workers/*/src",
)

# Baked into the test image by backend/Dockerfile.test, because `make test`
# mounts only backend/. Falls back to the repo checkout for a host-side run.
_SCAN_ROOT = Path("/repo-scan") if Path("/repo-scan").is_dir() else _REPO

_CREDENTIAL_MARKERS = (
    "api.anthropic.com",
    "api.openai.com",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    '"x-api-key"',
    "from anthropic import",
    # Added with OpenRouter support. A guard that lists only the providers that
    # existed when it was written stops being a guard the moment a new one is
    # added — the whole point is that NO application module holds a provider
    # credential, not that none holds one of two particular credentials.
    "openrouter.ai/api",
    "OPENROUTER_API_KEY",
)


def test_no_application_module_holds_a_provider_credential():
    """The migration's deliverable, repo-wide — the assertion the whole effort
    was for.

    Every other test in this file scans backend/app only, so each service could
    satisfy its own suite while the repo as a whole still egressed to a provider:
    that is exactly how two backend modules POSTed raw httpx to a provider
    through seven phases, and how voice-agent kept the last provider credential
    until phase 7. A per-service check cannot see a repo-wide property.

    Scanned as SOURCE TEXT, because the regression is someone reintroducing a
    direct client — which no import check inside one service's suite would ever
    see. Prose that needs to discuss a credential says so without spelling the
    literal (phase 8's precedent): reword the comment, never weaken the scan.

    litellm-config.yaml and .env are the legitimate holders and are not scanned.
    The proxy is the egress point; that is the whole design.

    This guard does NOT skip. The other services' source is baked into the test
    image (backend/Dockerfile.test) for the same reason litellm-config.yaml is:
    a guard that skips in the acceptance gate is not a guard. It asserts it
    actually saw every service, so a COPY going missing fails loudly instead of
    quietly narrowing the scan to nothing.
    """
    trees = [t for pattern in _OTHER_SERVICE_TREES
             for t in sorted(_SCAN_ROOT.glob(pattern)) if t.is_dir()]
    assert len(trees) >= 6, (
        f"expected at least 6 service source trees under {_SCAN_ROOT}, saw "
        f"{[str(t) for t in trees]} — the scan silently covered almost nothing. "
        "Check the /repo-scan COPY lines in backend/Dockerfile.test."
    )

    offenders: dict[str, list[str]] = {}
    for tree in [_APP, *trees]:
        root = _BACKEND if tree is _APP else _SCAN_ROOT
        for path in tree.rglob("*.py"):
            body = path.read_text(encoding="utf-8")
            hits = [marker for marker in _CREDENTIAL_MARKERS if marker in body]
            if hits:
                offenders[path.relative_to(root).as_posix()] = hits

    assert offenders == {}, (
        "provider credentials or direct provider egress found in application "
        f"code: {offenders}"
    )


_MANIFESTS = (
    "voice-agent/requirements.txt",
    "intake-core/pyproject.toml",
    "llm-core/pyproject.toml",
    "workers/*/requirements*.txt",
    "workers/*/production/requirements*.txt",
    "workers/*/pyproject.toml",
)


def _declares_provider_sdk(line: str) -> bool:
    """A dependency LINE that installs a provider SDK. Comments are prose."""
    stripped = line.split("#")[0].strip()
    if not stripped:
        return False
    return "anthropic" in stripped.lower()


def test_no_service_installs_a_provider_sdk():
    """The blind spot that outlived the source migration, twice.

    Every scan above reads source text, and source text cannot see a package
    that is INSTALLED but never imported. Two survived to the end of this effort
    that way, both in services whose source was already clean:

      * voice-agent kept pipecat's `[anthropic]` extra, the only thing that
        installs the SDK, so `import anthropic` still succeeded (0.49.0);
      * intake-context-builder kept a direct `anthropic==0.40.0` pin that phase 4
        left behind — `pip show` reported an empty Required-by.

    An installed SDK is a loaded gun: a direct client can be typed back in and
    every source guard in this file still passes. `anthropic` appearing in a
    COMMENT is fine and expected — several manifests explain why it is absent —
    so only the dependency part of each line is examined.
    """
    manifests = [m for pattern in _MANIFESTS
                 for m in sorted(_SCAN_ROOT.glob(pattern)) if m.is_file()]
    assert len(manifests) >= 4, (
        f"expected at least 4 dependency manifests under {_SCAN_ROOT}, saw "
        f"{[str(m) for m in manifests]}. Check the /repo-scan COPY lines in "
        "backend/Dockerfile.test."
    )

    offenders = {
        m.relative_to(_SCAN_ROOT).as_posix(): [
            line.strip() for line in m.read_text(encoding="utf-8").splitlines()
            if _declares_provider_sdk(line)
        ]
        for m in manifests
    }
    offenders = {path: lines for path, lines in offenders.items() if lines}

    assert offenders == {}, (
        f"a provider SDK is still installed by: {offenders}. Source being clean "
        "is not enough — see this test's docstring."
    )
