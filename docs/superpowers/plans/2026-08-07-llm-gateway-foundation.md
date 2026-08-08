# LLM Gateway Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a LiteLLM proxy container and a shared `llm-core` package that gives every service one provider-agnostic way to call a language model.

**Architecture:** A `litellm` container is the single egress point for text generation. Applications never import a provider SDK; they talk OpenAI-shaped HTTP to the proxy using the lightweight `openai` async client, wrapped by `llm-core` so call sites see normalized replies. Model names in config become aliases the proxy resolves to real providers, so switching a workload to a local Gemma is a config edit rather than a code change.

**Tech Stack:** Python 3.11, `openai>=1.40` and `httpx` (client), LiteLLM proxy (`ghcr.io/berriai/litellm:main-latest`), structlog, pytest + pytest-asyncio, Docker Compose. Result types are plain dataclasses — `llm-core` deliberately takes no pydantic dependency, since nothing here needs runtime validation.

**Source spec:** `docs/superpowers/specs/2026-08-07-provider-agnostic-llm-design.md`

## Global Constraints

- Python `>=3.11` for all packages, matching `intake-core/pyproject.toml`.
- `llm-core` is a **new sibling package** at repo root, installed from the repo-root build context exactly as `intake-core` is (`backend/Dockerfile:14`).
- `llm-core` must NOT depend on `anthropic`, `litellm`, or any other provider SDK. Its only permitted HTTP dependencies are `openai>=1.40,<2.0` (chat completions) and `httpx>=0.27,<1.0` (the gateway's `/model/info` probe).
- Every HTML element added anywhere in this project must carry a unique `id`. (No UI is added by this plan; the rule is stated because it is project-wide.)
- Secrets live in the root `.env`, never in committed files. `.env.example` documents names with empty values only.
- No API keys, secrets, certs, or `.env` files may be committed.
- Run `npm run build` before committing any change touching a Next.js app. (No app is touched by this plan.)
- Rebuild and restart affected containers after changes: `docker compose up -d --build <service>`.
- Commit after each task with a meaningful message.

## Implementation note: `openai` client, not the `litellm` SDK

The spec's §3 sketch showed `litellm.acompletion`. Now that the proxy is the chosen
deployment (spec decision 5), calling the LiteLLM *SDK* from inside each app would be
redundant — the proxy already speaks the OpenAI wire format, and the `litellm` package
pulls a large dependency tree into every image.

`llm-core` therefore uses `openai.AsyncOpenAI` pointed at the proxy. This is fully
consistent with the approved architecture ("every app speaks OpenAI-shaped HTTP to the
proxy") and strictly lighter. LiteLLM still runs — in the proxy container, where it
does the provider translation. Nothing about aliases, fallbacks, or provider routing
changes.

## File Structure

| Path | Responsibility |
|---|---|
| `llm-core/pyproject.toml` | Package metadata; deps `openai`, `httpx`, `structlog` |
| `llm-core/llm_core/__init__.py` | Public exports: `llm`, `LLMReply`, `ToolCall`, `LLMError`, `ToolEmulationError` |
| `llm-core/llm_core/types.py` | `ToolCall`, `LLMReply` — normalized result shapes, no vendor types |
| `llm-core/llm_core/errors.py` | `LLMError`, `ToolEmulationError` |
| `llm-core/llm_core/settings.py` | Reads `LLM_GATEWAY_URL`, `LITELLM_MASTER_KEY`, `LLM_FORCE_JSON_TOOLS`, `LLM_TIMEOUT_SECONDS` |
| `llm-core/llm_core/capabilities.py` | Fetches and caches per-alias function-calling support from the proxy |
| `llm-core/llm_core/emulation.py` | JSON-schema tool emulation: prompt building + reply validation |
| `llm-core/llm_core/client.py` | `complete()` and `stream_turn()` — the only file that touches `openai` |
| `llm-core/llm_core/fake.py` | `FakeLLM` test double + `fake_llm` pytest fixture |
| `llm-core/tests/` | Unit tests for all of the above |
| `litellm-config.yaml` | Alias → provider map, at repo root next to `docker-compose.yml` |
| `docker-compose.yml` | New `litellm` service |
| `Makefile` | New `verify` row; new `verify-local-llm` target |
| `.env.example` | New variables documented |

---

### Task 1: `llm-core` package skeleton with normalized result types

**Files:**
- Create: `llm-core/pyproject.toml`
- Create: `llm-core/llm_core/__init__.py`
- Create: `llm-core/llm_core/types.py`
- Create: `llm-core/llm_core/errors.py`
- Test: `llm-core/tests/test_types.py`
- Test: `llm-core/tests/test_errors.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ToolCall(*, id: str, name: str, arguments: dict[str, Any])`; `LLMReply(*, text: str, model: str, tool_calls: list[ToolCall] = [], finish_reason: str | None = None, emulated_tools: bool = False)`; `LLMReply.tool_call_named(name: str) -> ToolCall | None`; exceptions `LLMError(message, *, alias=None, status=None, provider=None)` and `ToolEmulationError(LLMError)`.

Both dataclasses are `kw_only=True`. Construct them by keyword everywhere — positional
construction is rejected at runtime by design, so field order can never become a silent
correctness bug in the five service migrations that build these types.

- [ ] **Step 1: Write the failing test**

Create `llm-core/tests/test_types.py`:

```python
from llm_core.types import LLMReply, ToolCall


def test_tool_call_named_finds_matching_call():
    reply = LLMReply(
        text="",
        tool_calls=[
            ToolCall(id="c1", name="emit_job_description", arguments={"title": "SRE"}),
            ToolCall(id="c2", name="mark_status", arguments={"status": "done"}),
        ],
        finish_reason="tool_calls",
        model="intake-jd",
    )

    found = reply.tool_call_named("mark_status")

    assert found is not None
    assert found.id == "c2"
    assert found.arguments == {"status": "done"}


def test_tool_call_named_returns_none_when_absent():
    reply = LLMReply(text="hi", tool_calls=[], finish_reason="stop", model="intake-jd")

    assert reply.tool_call_named("nope") is None


def test_reply_defaults_are_safe():
    reply = LLMReply(text="hi", model="intake-jd")

    assert reply.tool_calls == []
    assert reply.finish_reason is None
    assert reply.emulated_tools is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd llm-core && python -m pytest tests/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm_core'`

- [ ] **Step 3: Write the package skeleton and types**

Create `llm-core/pyproject.toml`:

```toml
[project]
name = "llm-core"
version = "0.1.0"
description = "Provider-agnostic LLM access shared across OpenRecruiting services"
requires-python = ">=3.11"
dependencies = [
    "openai>=1.40,<2.0",
    "httpx>=0.27,<1.0",
    "structlog>=24.1,<26.0",
]

[project.optional-dependencies]
test = [
    "pytest>=8.0,<9.0",
    "pytest-asyncio>=0.23,<1.0",
    "pytest-mock>=3.12",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["llm_core*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

Create `llm-core/llm_core/errors.py`:

```python
"""Errors raised by llm_core. Never surface a bare empty-string message: the
Anthropic-era HTTP invoker did exactly that and produced 'Failed to trigger job: '
in logs, which cost real debugging time.
"""

from __future__ import annotations


class LLMError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        alias: str | None = None,
        status: int | None = None,
        provider: str | None = None,
    ) -> None:
        detail = message or "unknown LLM failure"
        parts = [detail]
        if alias:
            parts.append(f"alias={alias}")
        if status is not None:
            parts.append(f"status={status}")
        if provider:
            parts.append(f"provider={provider}")
        super().__init__(" ".join(parts))
        self.alias = alias
        self.status = status
        self.provider = provider


class ToolEmulationError(LLMError):
    """A model without native tool support failed to return schema-valid JSON."""
```

Create `llm-core/llm_core/types.py`:

```python
"""Normalized LLM result shapes. No vendor types cross this boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, kw_only=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class LLMReply:
    text: str
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    emulated_tools: bool = False

    def tool_call_named(self, name: str) -> ToolCall | None:
        for call in self.tool_calls:
            if call.name == name:
                return call
        return None
```

Create `llm-core/llm_core/__init__.py`:

```python
from llm_core.errors import LLMError, ToolEmulationError
from llm_core.types import LLMReply, ToolCall

__all__ = ["LLMError", "LLMReply", "ToolCall", "ToolEmulationError"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd llm-core && pip install -e '.[test]' && python -m pytest tests/test_types.py -v`
Expected: PASS, 3 passed

- [ ] **Step 5: Commit**

```bash
git add llm-core/
git commit -m "feat(llm-core): package skeleton with normalized reply types"
```

---

### Task 2: Settings and capability detection

**Files:**
- Create: `llm-core/llm_core/settings.py`
- Create: `llm-core/llm_core/capabilities.py`
- Test: `llm-core/tests/test_capabilities.py`

**Interfaces:**
- Consumes: `LLMError` from Task 1.
- Produces: `get_settings() -> LLMSettings` with fields `gateway_url: str`, `api_key: str`, `force_json_tools: frozenset[str]`, `timeout_seconds: float`; `CapabilityCache(http_get)` with `async supports_tools(alias: str) -> bool` and `reset()`.

`http_get` is an async callable `(path: str) -> dict` so tests need no network.

- [ ] **Step 1: Write the failing test**

Create `llm-core/tests/test_capabilities.py`:

```python
import pytest

from llm_core.capabilities import CapabilityCache


def _model_info_payload():
    return {
        "data": [
            {"model_name": "intake-jd", "model_info": {"supports_function_calling": True}},
            {"model_name": "intake-jd-local", "model_info": {"supports_function_calling": False}},
            {"model_name": "mystery", "model_info": {}},
        ]
    }


async def test_reports_support_from_proxy():
    cache = CapabilityCache(http_get=lambda path: _async(_model_info_payload()))

    assert await cache.supports_tools("intake-jd") is True
    assert await cache.supports_tools("intake-jd-local") is False


async def test_missing_flag_defaults_to_supported():
    cache = CapabilityCache(http_get=lambda path: _async(_model_info_payload()))

    assert await cache.supports_tools("mystery") is True


async def test_unknown_alias_defaults_to_supported():
    cache = CapabilityCache(http_get=lambda path: _async(_model_info_payload()))

    assert await cache.supports_tools("never-heard-of-it") is True


async def test_forced_aliases_override_proxy():
    cache = CapabilityCache(
        http_get=lambda path: _async(_model_info_payload()),
        forced_json_aliases=frozenset({"intake-jd"}),
    )

    assert await cache.supports_tools("intake-jd") is False


async def test_proxy_failure_defaults_to_supported_and_does_not_raise():
    async def boom(path):
        raise RuntimeError("proxy down")

    cache = CapabilityCache(http_get=boom)

    assert await cache.supports_tools("intake-jd") is True


async def test_fetches_once_and_caches():
    calls = []

    async def counting(path):
        calls.append(path)
        return _model_info_payload()

    cache = CapabilityCache(http_get=counting)
    await cache.supports_tools("intake-jd")
    await cache.supports_tools("intake-jd-local")

    assert len(calls) == 1


async def _async(value):
    return value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd llm-core && python -m pytest tests/test_capabilities.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm_core.capabilities'`

- [ ] **Step 3: Write settings and capability cache**

Create `llm-core/llm_core/settings.py`:

```python
"""Configuration for reaching the LiteLLM gateway."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, kw_only=True)
class LLMSettings:
    gateway_url: str
    api_key: str
    force_json_tools: frozenset[str]
    timeout_seconds: float


@lru_cache(maxsize=1)
def get_settings() -> LLMSettings:
    raw_forced = os.environ.get("LLM_FORCE_JSON_TOOLS", "")
    forced = frozenset(a.strip() for a in raw_forced.split(",") if a.strip())
    return LLMSettings(
        gateway_url=os.environ.get("LLM_GATEWAY_URL", "http://litellm:4000").rstrip("/"),
        api_key=os.environ.get("LITELLM_MASTER_KEY", ""),
        force_json_tools=forced,
        timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
    )
```

Create `llm-core/llm_core/capabilities.py`:

```python
"""Per-alias function-calling support, read once from the proxy's /model/info.

Defaults to True on any uncertainty. A false negative would silently downgrade a
capable model to emulated tools, which is worse than a loud failure from a model
that genuinely cannot do tools.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

HttpGet = Callable[[str], Awaitable[dict[str, Any]]]


class CapabilityCache:
    def __init__(
        self,
        http_get: HttpGet,
        forced_json_aliases: frozenset[str] = frozenset(),
    ) -> None:
        self._http_get = http_get
        self._forced = forced_json_aliases
        self._map: dict[str, bool] | None = None
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._map = None

    async def supports_tools(self, alias: str) -> bool:
        if alias in self._forced:
            return False
        table = await self._load()
        return table.get(alias, True)

    async def _load(self) -> dict[str, bool]:
        if self._map is not None:
            return self._map
        async with self._lock:
            if self._map is not None:
                return self._map
            try:
                payload = await self._http_get("/model/info")
            except Exception as exc:  # noqa: BLE001 — never block a call on discovery
                # Do NOT memoize a failure. Caching {} here would combine with the
                # fail-open default below to report every alias tool-capable for the
                # rest of the process, which would send real tool definitions to the
                # Ollama aliases forever and permanently bypass emulation.
                logger.warning("llm_capability_probe_failed", error=str(exc))
                return {}

            table: dict[str, bool] = {}
            for entry in payload.get("data", []) or []:
                name = entry.get("model_name")
                if not name:
                    continue
                info = entry.get("model_info") or {}
                # Explicit True/False only. bool() would coerce a quoted YAML
                # "false" to True (unsafe) and an explicit null to False (defeats
                # the documented default).
                flag = info.get("supports_function_calling")
                table[name] = flag if isinstance(flag, bool) else True
            self._map = table
            logger.info("llm_capabilities_loaded", aliases=len(table))
            return self._map
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd llm-core && python -m pytest tests/test_capabilities.py -v`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add llm-core/
git commit -m "feat(llm-core): gateway settings and per-alias capability detection"
```

---

### Task 3: JSON-schema tool emulation

**Files:**
- Create: `llm-core/llm_core/emulation.py`
- Test: `llm-core/tests/test_emulation.py`

**Interfaces:**
- Consumes: `ToolCall` (Task 1), `ToolEmulationError` (Task 1).
- Produces: `build_emulation_instruction(tools: list[dict]) -> str`; `parse_emulated_reply(raw: str, tools: list[dict]) -> ToolCall`.

Tools arrive in OpenAI shape: `{"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}`.

- [ ] **Step 1: Write the failing test**

Create `llm-core/tests/test_emulation.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd llm-core && python -m pytest tests/test_emulation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm_core.emulation'`

- [ ] **Step 3: Write the emulation module**

Create `llm-core/llm_core/emulation.py`:

```python
"""Tool calling for models without native function calling.

The tool schema is rendered into the prompt and the reply is validated back into
the same ToolCall shape a native call produces, so callers cannot tell the
difference. Reliability is materially lower than native tool use — see the Risks
section of the design spec before pointing a scoring path at an emulated model.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from llm_core.errors import ToolEmulationError
from llm_core.types import ToolCall

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def build_emulation_instruction(tools: list[dict[str, Any]]) -> str:
    if not tools:
        return ""
    fn = tools[0].get("function", {})
    name = fn.get("name", "tool")
    schema = json.dumps(fn.get("parameters", {}), indent=2)
    description = fn.get("description", "")
    return (
        f"You must respond by calling the tool `{name}`.\n"
        f"{description}\n\n"
        "Reply with a single JSON object and nothing else — no prose, no code fence, "
        "no explanation. The object must conform to this JSON Schema:\n"
        f"{schema}\n"
    )


def _extract_json(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        raise ToolEmulationError("model returned an empty reply")

    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ToolEmulationError(f"model reply was not JSON: {text[:200]}")


def parse_emulated_reply(raw: str, tools: list[dict[str, Any]]) -> ToolCall:
    fn = tools[0].get("function", {})
    name = fn.get("name", "tool")
    parsed = _extract_json(raw)

    if not isinstance(parsed, dict):
        raise ToolEmulationError(f"expected a JSON object, got {type(parsed).__name__}")

    # Some models wrap the payload as {"name": ..., "arguments": {...}}.
    if set(parsed.keys()) >= {"name", "arguments"} and isinstance(parsed["arguments"], dict):
        parsed = parsed["arguments"]

    schema = fn.get("parameters", {}) or {}
    for required in schema.get("required", []) or []:
        if required not in parsed:
            raise ToolEmulationError(
                f"reply is missing required property '{required}' for tool '{name}'"
            )

    return ToolCall(id=f"emulated-{uuid.uuid4().hex[:8]}", name=name, arguments=parsed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd llm-core && python -m pytest tests/test_emulation.py -v`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add llm-core/
git commit -m "feat(llm-core): JSON-schema tool emulation for models without native tools"
```

---

### Task 4: `complete()` — the non-streaming call path

**Files:**
- Create: `llm-core/llm_core/client.py`
- Modify: `llm-core/llm_core/__init__.py`
- Test: `llm-core/tests/test_client_complete.py`

**Interfaces:**
- Consumes: `LLMReply`, `ToolCall`, `LLMError` (Task 1); `get_settings`, `CapabilityCache` (Task 2); `build_emulation_instruction`, `parse_emulated_reply` (Task 3).
- Produces: `LLMClient(openai_client=None, capabilities=None)` with
  `async complete(*, model: str, messages: list[dict], tools: list[dict] | None = None, system: str | None = None, max_tokens: int = 2048, temperature: float | None = None) -> LLMReply`.
  Module-level singleton `llm` and `get_client() -> LLMClient`.

`system` is a convenience: when given it is prepended as a `{"role": "system"}` message. This exists because 11 backend call sites currently pass Anthropic's separate `system=` argument.

- [ ] **Step 1: Write the failing test**

Create `llm-core/tests/test_client_complete.py`:

```python
import json
from types import SimpleNamespace

import pytest

from llm_core.client import LLMClient
from llm_core.errors import LLMError

TOOL = {
    "type": "function",
    "function": {
        "name": "emit_job_description",
        "description": "Return the structured job description.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
    },
}


class FakeCaps:
    def __init__(self, supported: bool = True):
        self.supported = supported
        self.asked = []

    async def supports_tools(self, alias):
        self.asked.append(alias)
        return self.supported


class FakeCompletions:
    def __init__(self, response, recorder):
        self._response = response
        self._recorder = recorder

    async def create(self, **kwargs):
        self._recorder.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _openai_stub(response, recorder):
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(response, recorder)))


def _text_response(text, finish="stop"):
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)], model="x"
    )


def _tool_response(name, args: dict):
    call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )
    message = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")], model="x"
    )


async def test_returns_plain_text():
    sent = []
    client = LLMClient(openai_client=_openai_stub(_text_response("hello"), sent), capabilities=FakeCaps())

    reply = await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert reply.text == "hello"
    assert reply.tool_calls == []
    assert reply.emulated_tools is False


async def test_system_argument_becomes_a_system_message():
    sent = []
    client = LLMClient(openai_client=_openai_stub(_text_response("ok"), sent), capabilities=FakeCaps())

    await client.complete(
        model="intake-jd", system="be terse", messages=[{"role": "user", "content": "hi"}]
    )

    assert sent[0]["messages"][0] == {"role": "system", "content": "be terse"}
    assert sent[0]["messages"][1] == {"role": "user", "content": "hi"}


async def test_native_tool_call_is_normalized():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_tool_response("emit_job_description", {"title": "SRE"}), sent),
        capabilities=FakeCaps(supported=True),
    )

    reply = await client.complete(
        model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
    )

    assert reply.emulated_tools is False
    call = reply.tool_call_named("emit_job_description")
    assert call is not None
    assert call.arguments == {"title": "SRE"}
    assert sent[0]["tools"] == [TOOL]


async def test_falls_back_to_emulation_when_model_lacks_tools():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response('{"title": "SRE"}'), sent),
        capabilities=FakeCaps(supported=False),
    )

    reply = await client.complete(
        model="intake-jd-local", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
    )

    assert reply.emulated_tools is True
    assert reply.tool_call_named("emit_job_description").arguments == {"title": "SRE"}
    # The real tools param must NOT be sent to a model that cannot handle it.
    assert "tools" not in sent[0]
    assert sent[0]["response_format"] == {"type": "json_object"}
    assert "emit_job_description" in sent[0]["messages"][0]["content"]


async def test_upstream_failure_raises_llmerror_with_alias():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(RuntimeError("upstream exploded"), sent),
        capabilities=FakeCaps(),
    )

    with pytest.raises(LLMError) as exc:
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert "intake-jd" in str(exc.value)
    assert "upstream exploded" in str(exc.value)


async def test_empty_upstream_message_still_produces_readable_error():
    sent = []
    client = LLMClient(openai_client=_openai_stub(RuntimeError(""), sent), capabilities=FakeCaps())

    with pytest.raises(LLMError) as exc:
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert str(exc.value).strip() != ""
    assert "unknown LLM failure" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd llm-core && python -m pytest tests/test_client_complete.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm_core.client'`

- [ ] **Step 3: Write the client**

Create `llm-core/llm_core/client.py`:

```python
"""The only module in the codebase that speaks to an LLM endpoint.

Talks OpenAI-shaped HTTP to the LiteLLM gateway. Model names are aliases the
gateway resolves to real providers, so provider choice is configuration.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx
import structlog
from openai import AsyncOpenAI

from llm_core.capabilities import CapabilityCache
from llm_core.emulation import build_emulation_instruction, parse_emulated_reply
from llm_core.errors import LLMError
from llm_core.settings import get_settings
from llm_core.types import LLMReply, ToolCall

logger = structlog.get_logger(__name__)


class LLMClient:
    def __init__(self, openai_client: Any = None, capabilities: Any = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._client = openai_client or AsyncOpenAI(
            base_url=f"{settings.gateway_url}/v1",
            api_key=settings.api_key or "not-needed",
            timeout=settings.timeout_seconds,
            max_retries=0,  # the gateway owns retries
        )
        self._caps = capabilities or CapabilityCache(
            http_get=self._gateway_get,
            forced_json_aliases=settings.force_json_tools,
        )

    async def _gateway_get(self, path: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._settings.api_key}"}
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(f"{self._settings.gateway_url}{path}", headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float | None = None,
    ) -> LLMReply:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        outgoing = list(messages)
        emulate = False

        if tools:
            emulate = not await self._caps.supports_tools(model)
            if emulate:
                instruction = build_emulation_instruction(tools)
                outgoing = [{"role": "system", "content": instruction}, *outgoing]
                payload["response_format"] = {"type": "json_object"}
            else:
                payload["tools"] = tools

        if system:
            outgoing = [{"role": "system", "content": system}, *outgoing]

        payload["messages"] = outgoing

        try:
            response = await self._client.chat.completions.create(**payload)
        except Exception as exc:  # noqa: BLE001 — normalize every provider failure
            raise LLMError(str(exc), alias=model) from exc

        choice = response.choices[0]
        text = choice.message.content or ""

        if emulate:
            call = parse_emulated_reply(text, tools or [])
            return LLMReply(
                text="",
                model=model,
                tool_calls=[call],
                finish_reason=choice.finish_reason,
                emulated_tools=True,
            )

        calls: list[ToolCall] = []
        for raw in getattr(choice.message, "tool_calls", None) or []:
            try:
                args = json.loads(raw.function.arguments or "{}")
            except json.JSONDecodeError:
                logger.warning(
                    "llm_tool_arguments_invalid",
                    alias=model,
                    name=raw.function.name,
                    raw=(raw.function.arguments or "")[:300],
                )
                args = {}
            calls.append(ToolCall(id=raw.id, name=raw.function.name, arguments=args))

        return LLMReply(
            text=text,
            model=model,
            tool_calls=calls,
            finish_reason=choice.finish_reason,
        )


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
```

Replace `llm-core/llm_core/__init__.py` with:

```python
from llm_core.client import LLMClient, get_client
from llm_core.errors import LLMError, ToolEmulationError
from llm_core.types import LLMReply, ToolCall

__all__ = [
    "LLMClient",
    "LLMError",
    "LLMReply",
    "ToolCall",
    "ToolEmulationError",
    "get_client",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd llm-core && pip install -e '.[test]' && python -m pytest tests/ -v`
Expected: PASS, 21 passed (3 types + 6 capabilities + 6 emulation + 6 client)

- [ ] **Step 5: Commit**

```bash
git add llm-core/
git commit -m "feat(llm-core): complete() with native and emulated tool calling"
```

---

### Task 5: `stream_turn()` — the streaming call path

**Files:**
- Modify: `llm-core/llm_core/client.py`
- Test: `llm-core/tests/test_client_stream.py`

**Interfaces:**
- Consumes: everything from Task 4.
- Produces: `LLMClient.stream_turn(*, model, messages, tools=None, system=None, max_tokens=2048) -> AsyncIterator[tuple[str, Any]]` yielding `('text', str)`, `('tool_call', {"id", "name", "input"})`, `('done', {"text", "stop_reason"})`.

This contract is copied deliberately from `backend/app/services/intake/anthropic_stream.py:25-33` so `text_runner` and its tests need no change when the backend migrates in a later phase. Tool calls are emitted only once their argument JSON is fully assembled.

- [ ] **Step 1: Write the failing test**

Create `llm-core/tests/test_client_stream.py`:

```python
from types import SimpleNamespace

from llm_core.client import LLMClient


class FakeCaps:
    def __init__(self, supported=True):
        self.supported = supported

    async def supports_tools(self, alias):
        return self.supported


def _chunk(content=None, tool=None, finish=None):
    delta = SimpleNamespace(content=content, tool_calls=tool)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)])


def _tool_delta(index, call_id=None, name=None, args=None):
    return [
        SimpleNamespace(
            index=index,
            id=call_id,
            function=SimpleNamespace(name=name, arguments=args),
        )
    ]


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self._chunks:
            yield c


def _openai_stub(chunks, recorder):
    class Completions:
        async def create(self, **kwargs):
            recorder.append(kwargs)
            return FakeStream(chunks)

    return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))


async def _collect(iterator):
    return [event async for event in iterator]


async def test_streams_text_then_done():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub([_chunk(content="Hel"), _chunk(content="lo"), _chunk(finish="stop")], sent),
        capabilities=FakeCaps(),
    )

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    assert ("text", "Hel") in events
    assert ("text", "lo") in events
    kind, payload = events[-1]
    assert kind == "done"
    assert payload["text"] == "Hello"
    assert payload["stop_reason"] == "stop"


async def test_assembles_tool_call_across_chunks():
    sent = []
    chunks = [
        _chunk(tool=_tool_delta(0, call_id="call_1", name="update_answer", args='{"qid"')),
        _chunk(tool=_tool_delta(0, args=': "q4_must_haves"}')),
        _chunk(finish="tool_calls"),
    ]
    client = LLMClient(openai_client=_openai_stub(chunks, sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    tool_events = [e for e in events if e[0] == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0][1] == {
        "id": "call_1",
        "name": "update_answer",
        "input": {"qid": "q4_must_haves"},
    }


async def test_malformed_tool_json_yields_empty_input_not_a_crash():
    sent = []
    chunks = [
        _chunk(tool=_tool_delta(0, call_id="call_1", name="update_answer", args="{not json")),
        _chunk(finish="tool_calls"),
    ]
    client = LLMClient(openai_client=_openai_stub(chunks, sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    tool_events = [e for e in events if e[0] == "tool_call"]
    assert tool_events[0][1]["input"] == {}


async def test_stream_flag_and_system_message_are_sent():
    sent = []
    client = LLMClient(openai_client=_openai_stub([_chunk(finish="stop")], sent), capabilities=FakeCaps())

    await _collect(
        client.stream_turn(
            model="debrief-chat", system="be terse", messages=[{"role": "user", "content": "hi"}]
        )
    )

    assert sent[0]["stream"] is True
    assert sent[0]["messages"][0] == {"role": "system", "content": "be terse"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd llm-core && python -m pytest tests/test_client_stream.py -v`
Expected: FAIL with `AttributeError: 'LLMClient' object has no attribute 'stream_turn'`

- [ ] **Step 3: Add `stream_turn` to `LLMClient`**

Append this method to the `LLMClient` class in `llm-core/llm_core/client.py`, directly after `complete`:

```python
    async def stream_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Stream one assistant turn as tagged events.

        ('text', str)        — incremental prose
        ('tool_call', {...}) — a completed call: {id, name, input}
        ('done', {...})      — {text, stop_reason}

        Contract copied from the Anthropic-era wrapper so consumers do not change.
        """
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": True,
        }

        outgoing = list(messages)
        if tools:
            if await self._caps.supports_tools(model):
                payload["tools"] = tools
            else:
                outgoing = [
                    {"role": "system", "content": build_emulation_instruction(tools)},
                    *outgoing,
                ]
        if system:
            outgoing = [{"role": "system", "content": system}, *outgoing]
        payload["messages"] = outgoing

        try:
            stream = await self._client.chat.completions.create(**payload)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(str(exc), alias=model) from exc

        text_parts: list[str] = []
        pending: dict[int, dict[str, Any]] = {}
        stop_reason: str | None = None

        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = getattr(choice, "delta", None)

            if choice.finish_reason:
                stop_reason = choice.finish_reason

            if delta is None:
                continue

            content = getattr(delta, "content", None)
            if content:
                text_parts.append(content)
                yield ("text", content)

            for raw in getattr(delta, "tool_calls", None) or []:
                slot = pending.setdefault(raw.index, {"id": None, "name": None, "buf": ""})
                if getattr(raw, "id", None):
                    slot["id"] = raw.id
                fn = getattr(raw, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["buf"] += fn.arguments

        for _, slot in sorted(pending.items()):
            try:
                parsed = json.loads(slot["buf"]) if slot["buf"] else {}
            except json.JSONDecodeError:
                logger.warning(
                    "llm_stream_tool_json_invalid",
                    alias=model,
                    name=slot["name"],
                    buf=slot["buf"][:300],
                )
                parsed = {}
            yield ("tool_call", {"id": slot["id"], "name": slot["name"], "input": parsed})

        yield ("done", {"text": "".join(text_parts), "stop_reason": stop_reason})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd llm-core && python -m pytest tests/ -v`
Expected: PASS, 25 passed

- [ ] **Step 5: Commit**

```bash
git add llm-core/
git commit -m "feat(llm-core): stream_turn() preserving the tagged event contract"
```

---

### Task 6: `FakeLLM` test double and pytest fixture

**Files:**
- Create: `llm-core/llm_core/fake.py`
- Create: `llm-core/llm_core/pytest_plugin.py`
- Modify: `llm-core/pyproject.toml` (register the plugin entry point)
- Test: `llm-core/tests/test_fake.py`

**Interfaces:**
- Consumes: `LLMReply`, `ToolCall` (Task 1).
- Produces: `FakeLLM` with `queue_text(text)`, `queue_tool_call(name, arguments)`, `queue_error(exc)`, `calls: list[dict]`, and the same `complete` / `stream_turn` signatures as `LLMClient`. Pytest fixture `fake_llm` yields a `FakeLLM`.

This exists so the 26 test files migrating in later phases never encode a vendor response shape again.

- [ ] **Step 1: Write the failing test**

Create `llm-core/tests/test_fake.py`:

```python
import pytest

from llm_core.fake import FakeLLM


async def test_queued_text_is_returned():
    fake = FakeLLM()
    fake.queue_text("hello")

    reply = await fake.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert reply.text == "hello"


async def test_queued_tool_call_is_returned():
    fake = FakeLLM()
    fake.queue_tool_call("emit_job_description", {"title": "SRE"})

    reply = await fake.complete(model="intake-jd", messages=[], tools=[])

    call = reply.tool_call_named("emit_job_description")
    assert call.arguments == {"title": "SRE"}


async def test_records_calls_for_assertions():
    fake = FakeLLM()
    fake.queue_text("ok")

    await fake.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}], system="be terse")

    assert fake.calls[0]["model"] == "intake-jd"
    assert fake.calls[0]["system"] == "be terse"


async def test_queued_error_is_raised():
    fake = FakeLLM()
    fake.queue_error(RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await fake.complete(model="intake-jd", messages=[])


async def test_stream_turn_replays_queued_text_then_done():
    fake = FakeLLM()
    fake.queue_text("hi there")

    events = [e async for e in fake.stream_turn(model="debrief-chat", messages=[])]

    assert ("text", "hi there") in events
    assert events[-1][0] == "done"
    assert events[-1][1]["text"] == "hi there"


async def test_running_dry_raises_a_clear_error():
    fake = FakeLLM()

    with pytest.raises(AssertionError, match="no queued response"):
        await fake.complete(model="intake-jd", messages=[])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd llm-core && python -m pytest tests/test_fake.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm_core.fake'`

- [ ] **Step 3: Write the fake and the plugin**

Create `llm-core/llm_core/fake.py`:

```python
"""In-memory stand-in for LLMClient.

Tests queue outcomes and assert on recorded calls. Nothing here knows about any
provider's wire format, which is the entire point.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from llm_core.types import LLMReply, ToolCall


class FakeLLM:
    def __init__(self) -> None:
        self._queue: list[Any] = []
        self.calls: list[dict[str, Any]] = []

    def queue_text(self, text: str) -> None:
        self._queue.append(LLMReply(text=text, model="fake", finish_reason="stop"))

    def queue_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        self._queue.append(
            LLMReply(
                text="",
                model="fake",
                tool_calls=[ToolCall(id=f"fake-{name}", name=name, arguments=arguments)],
                finish_reason="tool_calls",
            )
        )

    def queue_reply(self, reply: LLMReply) -> None:
        self._queue.append(reply)

    def queue_error(self, exc: Exception) -> None:
        self._queue.append(exc)

    def _next(self, record: dict[str, Any]) -> LLMReply:
        self.calls.append(record)
        assert self._queue, (
            "FakeLLM has no queued response — call queue_text/queue_tool_call/"
            "queue_error before the code under test runs"
        )
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float | None = None,
    ) -> LLMReply:
        return self._next(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )

    async def stream_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[tuple[str, Any]]:
        reply = self._next(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "system": system,
                "max_tokens": max_tokens,
                "streaming": True,
            }
        )
        if reply.text:
            yield ("text", reply.text)
        for call in reply.tool_calls:
            yield ("tool_call", {"id": call.id, "name": call.name, "input": call.arguments})
        yield ("done", {"text": reply.text, "stop_reason": reply.finish_reason})
```

Create `llm-core/llm_core/pytest_plugin.py`:

```python
import pytest

from llm_core.fake import FakeLLM


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
```

In `llm-core/pyproject.toml`, add this block after `[tool.setuptools.packages.find]`:

```toml
[project.entry-points.pytest11]
llm_core = "llm_core.pytest_plugin"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd llm-core && pip install -e '.[test]' && python -m pytest tests/ -v`
Expected: PASS, 31 passed

- [ ] **Step 5: Commit**

```bash
git add llm-core/
git commit -m "feat(llm-core): FakeLLM double and fake_llm pytest fixture"
```

---

### Task 7: LiteLLM proxy container and alias configuration

**Files:**
- Create: `litellm-config.yaml`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `Makefile`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a reachable gateway at `http://litellm:4000` inside the compose network and `http://localhost:4000` from the host, serving aliases `intake-jd`, `intake-jd-local`, `debrief-chat`, `screening-generator`, `screening-assessor`, `persona-reduce`, `route-intent`, `signal-extract`, `resume-extract`, `candidate-detect`, `end-state`, `voice-intake`, `feedback-condense`, `context-synthesize`.

Alias names are taken from the settings they replace in `backend/app/config.py` so the mapping is obvious at a glance.

- [ ] **Step 1: Write the gateway config**

Create `litellm-config.yaml` at the repo root:

```yaml
# Alias -> provider map for the LiteLLM gateway.
#
# Applications only ever send an alias. To move a workload onto a different
# provider, change litellm_params here and restart this service — no app rebuild.
#
# IMPORTANT: two entries sharing a model_name is NOT an override, it declares a
# load-balancing group and requests will round-robin between them. Local variants
# therefore use a distinct '-local' alias.

model_list:
  - model_name: intake-jd
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: intake-jd-local
    litellm_params:
      model: ollama_chat/gemma4:latest
      api_base: os.environ/OLLAMA_API_BASE
    model_info: {supports_function_calling: false}

  - model_name: debrief-chat
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: screening-generator
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: screening-assessor
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: persona-reduce
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: route-intent
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: signal-extract
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: resume-extract
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: candidate-detect
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: end-state
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: voice-intake
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: feedback-condense
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: context-synthesize
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  # --- Smoke-test aliases: one per provider, used by the cross-provider suite ---
  - model_name: smoke-anthropic
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: smoke-openai
    litellm_params:
      model: openai/gpt-5.6-terra
      api_key: os.environ/OPENAI_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: smoke-local
    litellm_params:
      model: ollama_chat/gemma4:latest
      api_base: os.environ/OLLAMA_API_BASE
    model_info: {supports_function_calling: false}

  - model_name: gemma-local
    litellm_params:
      model: ollama_chat/gemma4:latest
      api_base: os.environ/OLLAMA_API_BASE
    model_info: {supports_function_calling: false}

litellm_settings:
  drop_params: true        # silently drop params a provider does not accept
  num_retries: 2
  request_timeout: 120

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

- [ ] **Step 2: Add the service to compose**

In `docker-compose.yml`, insert this service immediately before the `backend:` service:

```yaml
  # Single egress point for text generation. Applications send an alias; this
  # resolves it to a provider. See litellm-config.yaml.
  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    volumes:
      - ./litellm-config.yaml:/app/config.yaml:ro
    ports: ["4000:4000"]
    env_file: [.env]
    # Lets the container reach an Ollama server running on the host.
    extra_hosts: ["host.docker.internal:host-gateway"]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://localhost:4000/health/liveliness')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    restart: unless-stopped
```

Then add `litellm` to the backend's `depends_on` list, changing `backend:`'s
`depends_on: [feedback-agent, intake-agent, intake-context-builder]` to:

```yaml
    depends_on: [feedback-agent, intake-agent, intake-context-builder, litellm]
```

- [ ] **Step 3: Document the new variables**

Append to `.env.example`:

```bash
# --- LLM gateway -------------------------------------------------------------
# Applications talk to the LiteLLM proxy, never to a provider directly.
LLM_GATEWAY_URL=http://litellm:4000
# Shared secret the apps present to the gateway. Generate one: openssl rand -hex 32
LITELLM_MASTER_KEY=
# Optional: comma-separated aliases forced onto emulated JSON tool calling,
# for when the gateway cannot report a model's capabilities.
LLM_FORCE_JSON_TOOLS=
# Per-request timeout the apps apply, in seconds.
LLM_TIMEOUT_SECONDS=60
# Where a local Ollama is listening, as seen from inside a container.
OLLAMA_API_BASE=http://host.docker.internal:11434
```

- [ ] **Step 4: Add verify coverage**

In `Makefile`, add this line to the `verify` target, directly after the `backend` line:

```makefile
	@curl -fsS --max-time 5 http://localhost:4000/health/liveliness >/dev/null 2>&1 && echo "  ok    litellm         http://localhost:4000"        || echo "  DOWN  litellm         http://localhost:4000  (needs LITELLM_MASTER_KEY)"
```

Add `verify-local-llm` to the `.PHONY` line and append this target at the end of the file:

```makefile
verify-local-llm: ## Prove the gateway reaches a local Ollama model
	@echo "Checking Ollama is up on the host..."
	@curl -fsS --max-time 5 http://localhost:11434/api/tags >/dev/null 2>&1 \
		&& echo "  ok    ollama          http://localhost:11434" \
		|| { echo "  DOWN  ollama — start it with: ollama serve"; exit 1; }
	@echo "Asking the gateway for gemma-local..."
	@KEY=$$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-); \
	curl -fsS --max-time 120 http://localhost:4000/v1/chat/completions \
		-H "Authorization: Bearer $$KEY" \
		-H "Content-Type: application/json" \
		-d '{"model":"gemma-local","messages":[{"role":"user","content":"Reply with the single word: ready"}],"max_tokens":16}' \
		| python3 -c "import sys,json; d=json.load(sys.stdin); print('  reply:', d['choices'][0]['message']['content'].strip())"
```

- [ ] **Step 5: Bring the gateway up and verify it**

```bash
# Generate a key if .env has none yet, then start the gateway.
grep -q '^LITELLM_MASTER_KEY=.\+' .env || echo "LITELLM_MASTER_KEY=$(openssl rand -hex 32)" >> .env
grep -q '^OLLAMA_API_BASE=' .env || echo "OLLAMA_API_BASE=http://host.docker.internal:11434" >> .env
docker compose up -d --build litellm
docker compose logs --tail 30 litellm
make verify
```

Expected: `make verify` prints `ok    litellm         http://localhost:4000`.

Then confirm alias resolution and capability reporting:

```bash
source .env
curl -fsS http://localhost:4000/model/info -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  | python3 -c "import sys,json; [print(m['model_name'], m.get('model_info',{}).get('supports_function_calling')) for m in json.load(sys.stdin)['data']]"
```

Expected: 15 aliases listed, `intake-jd-local` and `gemma-local` reporting `False`.

- [ ] **Step 6: Commit**

```bash
git add litellm-config.yaml docker-compose.yml .env.example Makefile
git commit -m "feat(llm): add LiteLLM gateway container with alias configuration"
```

---

### Task 8: End-to-end proof against both a hosted and a local model

**Files:**
- Create: `llm-core/tests/integration/test_gateway_live.py`
- Modify: `docs/e2e-checklist.md`

**Interfaces:**
- Consumes: `LLMClient` (Tasks 4-5), the running gateway (Task 7).
- Produces: nothing later tasks depend on. This task exists to prove the foundation before five services are migrated onto it.

These tests are marked `live_gateway` and are excluded from default runs, following the `live_infra` precedent in `cortex-backend`'s Makefile target.

- [ ] **Step 1: Write the live integration test**

Create `llm-core/tests/integration/test_gateway_live.py`:

```python
"""Live checks against a running gateway. Excluded from default runs.

Run with:  python -m pytest tests/integration -m live_gateway -v
Requires:  docker compose up -d litellm   (and ollama serve, for the local test)
"""

import os

import pytest

from llm_core.client import LLMClient

pytestmark = pytest.mark.live_gateway

JD_TOOL = {
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


@pytest.fixture(autouse=True)
def _gateway_env(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", os.environ.get("LLM_GATEWAY_URL", "http://localhost:4000"))
    from llm_core import settings

    settings.get_settings.cache_clear()


async def test_hosted_alias_returns_text():
    reply = await LLMClient().complete(
        model="intake-jd",
        messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        max_tokens=16,
    )

    assert "ready" in reply.text.lower()
    assert reply.emulated_tools is False


async def test_hosted_alias_makes_a_native_tool_call():
    reply = await LLMClient().complete(
        model="intake-jd",
        messages=[{"role": "user", "content": "Job: Staff SRE, based in Remote - US."}],
        tools=[JD_TOOL],
        max_tokens=512,
    )

    call = reply.tool_call_named("emit_job_description")
    assert call is not None
    assert reply.emulated_tools is False
    assert "SRE" in call.arguments.get("title", "")


async def test_local_gemma_returns_text():
    reply = await LLMClient().complete(
        model="gemma-local",
        messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        max_tokens=16,
    )

    assert reply.text.strip() != ""


async def test_local_gemma_tool_call_is_emulated_and_valid():
    reply = await LLMClient().complete(
        model="gemma-local",
        messages=[{"role": "user", "content": "Job: Staff SRE, based in Remote - US."}],
        tools=[JD_TOOL],
        max_tokens=512,
    )

    assert reply.emulated_tools is True
    call = reply.tool_call_named("emit_job_description")
    assert call is not None
    assert "title" in call.arguments
```

Register the marker by adding to `llm-core/pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
markers = ["live_gateway: needs a running LiteLLM gateway (and Ollama for local models)"]
```

- [ ] **Step 2: Run the unit suite to confirm the live tests are excluded**

Run: `cd llm-core && python -m pytest tests/ -m "not live_gateway" -v`
Expected: PASS, 31 passed, 4 deselected

- [ ] **Step 3: Run the live tests against the gateway**

```bash
docker compose up -d litellm
ollama serve &            # if not already running
ollama pull gemma4
cd llm-core && LLM_GATEWAY_URL=http://localhost:4000 python -m pytest tests/integration -m live_gateway -v
```

Expected: 4 passed. If `test_local_gemma_tool_call_is_emulated_and_valid` fails, the
emulation prompt needs tightening for this model — fix `build_emulation_instruction`
in `llm_core/emulation.py` and re-run. Do not proceed to phase 2 with this red.

- [ ] **Step 4: Record the result in the checklist**

In `docs/e2e-checklist.md`, add to the Tests table:

```markdown
| llm-core (pytest) | `python -m pytest -m "not live_gateway"` | **31 passed**, 4 deselected |
```

And add a row to the Infrastructure table:

```markdown
| 13 | `litellm` gateway healthy and resolving aliases | **PASS** — 15 aliases via `/model/info` |
```

- [ ] **Step 5: Commit**

```bash
git add llm-core/ docs/e2e-checklist.md
git commit -m "test(llm-core): live gateway proof for hosted and local models"
```

---

## Phase map — what follows this plan

This plan delivers phase 1 of six. The remaining phases each migrate one service
onto `llm_core` and each gets its own plan, written once this foundation's API is
real and proven by Task 8:

| Phase | Service | Scale |
|---|---|---|
| 2 | `backend` non-streaming | 11 call sites, 17 test files |
| 3 | `backend` streaming | `anthropic_stream.py` → `llm_stream.py`; `text_runner` untouched |
| 4 | `intake-core` + `intake-context-builder` | 3 call sites, 7 test files, tool schemas to OpenAI shape |
| 5 | `feedback-agent` | repoint the hand-rolled httpx client; 0 test files |
| 6 | `voice-agent` | pipecat `OpenAILLMService` swap; 2 test files; loses prompt caching |

They are deliberately not written yet. Their tasks consist of rewriting exact call
sites against `llm.complete()` and `llm.stream_turn()`, and writing those before
Task 8 has proven the signatures against a live gateway would mean inventing code
against an unvalidated interface.

## Definition of done for this plan

- `llm-core` unit suite green: 31 passed.
- `llm-core` live suite green: 4 passed, covering native tools on Claude and
  emulated tools on Gemma.
- `make verify` shows `ok    litellm`.
- `make verify-local-llm` prints a reply from the local model.
- No existing suite regresses: backend 2105, cortex-backend 486, recruiter-app 1224,
  landing 31, cortex-mcp 152.
- No provider SDK added to any application image; `anthropic` pins remain untouched
  until phase 2, so this phase is purely additive and safely revertible.
