"""Ask a model to do the four things this stack needs, and report what happened.

WHY A LIVE PROBE WHEN QUIRKS ARE ALREADY DERIVED. Catalogue metadata says what a
model CLAIMS. This says what it DOES. The two disagree often enough to matter:
a model can advertise `tools` and still return prose, and nothing downstream
would report it — a workload that streams and sends tools does not degrade when
its model cannot call one, it silently stops recording answers.

The four checks mirror llm-core/tests/integration/test_gateway_live.py exactly,
because that suite is what defines "works" for this codebase. Kept as its own
copy rather than importing it: setup-ui deliberately imports no application code
so it stays reachable on a completely unconfigured stack.

THROUGH THE GATEWAY, NEVER DIRECT. The model id is sent to litellm's wildcard
route, so this process passes a model NAME and never a provider key. That keeps
the gateway the single egress point, which is the property the whole migration
was for. It is also why any model of a configured provider can be tested without
first writing it into the config and restarting — but the PROVIDER does have to
be saved, because the wildcard route is what the save creates.

WITH THE QUIRKS, NOT WITHOUT THEM. The wildcard route carries no per-model
settings, so the caller must pass the same params the generator would write.
Skipping that measures a configuration nobody will ever run: the first version
of this did, and failed z-ai/glm-5.2 on an empty reply and a silent stream —
both of which are exactly what its reasoning quirk fixes.

Roughly $0.0005 on a mid-priced model — four calls with small max_tokens. Cost
is reported back so the user sees what a test spent.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

# Deliberately identical to the live suite's fixtures.
_JD_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_job_description",
        "description": "Return the structured job description.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "location": {"type": "string"}},
            "required": ["title"],
        },
    },
}
_CANDIDATE_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_candidate_profile",
        "description": "Return the structured profile of a job applicant.",
        "parameters": {
            "type": "object",
            "properties": {"full_name": {"type": "string"}, "headline": {"type": "string"}},
            "required": ["full_name"],
        },
    },
}
_JOB_PROMPT = "Job opening: Staff SRE, based in Remote - US. Record it."

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class ProbeResult:
    model: str
    provider: str
    checks: list[Check] = field(default_factory=list)
    cost_usd: float = 0.0
    #: True only when every check passed. The UI gates binding on this.
    ok: bool = False
    #: Set when the model works but something about it needs saying.
    warning: str = ""
    #: Human-readable list of the quirks the probe ran WITH, so a pass is never
    #: mistaken for "this model needs no configuration".
    applied: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProbeError(Exception):
    """The probe could not be run at all. Distinct from a model failing it."""


class Prober:
    def __init__(self, gateway_url: str, master_key: str):
        self._base = gateway_url.rstrip("/")
        self._key = master_key

    async def _post(self, client: httpx.AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
        resp = await client.post(
            f"{self._base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            json=body,
        )
        if resp.status_code >= 400:
            raise ProbeError(_explain(resp.status_code, resp.text))
        return resp.json()

    async def run(
        self,
        provider_prefix: str,
        provider_id: str,
        model_id: str,
        quirk_params: dict[str, Any] | None = None,
        quirk_notes: tuple[str, ...] = (),
    ) -> ProbeResult:
        """Four calls against `<prefix>/<model id>` through the wildcard route.

        `quirk_params` MUST be the same params the generator would write for this
        model. The wildcard route carries no quirks of its own, so without them
        this measures a configuration nobody will ever run: the first version
        did exactly that and failed z-ai/glm-5.2 on an empty reply and a silent
        stream — both of which are precisely what its reasoning quirk fixes. A
        probe that condemns a model the product would have used correctly is
        worse than no probe.
        """
        if not self._key:
            raise ProbeError(
                "The gateway master key is not set, so nothing can be tested. Fill in "
                "LITELLM_MASTER_KEY under AI models first."
            )
        target = f"{provider_prefix}/{model_id}"
        extra = dict(quirk_params or {})
        result = ProbeResult(model=model_id, provider=provider_id, applied=quirk_notes)
        cost = 0.0

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # 1. Plain text.
            data = await self._post(
                client,
                {
                    "model": target,
                    "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
                    "max_tokens": 64,
                    **extra,
                },
            )
            cost += _cost_of(data)
            text = (data["choices"][0]["message"].get("content") or "").strip()
            finish = data["choices"][0].get("finish_reason")
            if text:
                result.checks.append(Check("Returns text", True, repr(text[:60])))
            else:
                # The signature of a reasoning model with no budget left. Named
                # explicitly because "empty reply" alone sends people hunting for
                # a network fault.
                hint = (
                    " — it spent the whole token budget on hidden reasoning before "
                    "answering, which is what the reasoning quirk exists to fix"
                    if finish == "length"
                    else ""
                )
                result.checks.append(
                    Check("Returns text", False, f"empty reply (finish_reason={finish}){hint}")
                )

            # 2. Native tool call with typed arguments.
            data = await self._post(
                client,
                {
                    "model": target,
                    "messages": [{"role": "user", "content": _JOB_PROMPT}],
                    "tools": [_JD_TOOL],
                    "max_tokens": 256,
                    **extra,
                },
            )
            cost += _cost_of(data)
            call = _first_tool_call(data, "emit_job_description")
            if call is None:
                result.checks.append(
                    Check("Calls a tool", False, "returned prose instead of a tool call")
                )
            elif not isinstance(call.get("title"), str):
                result.checks.append(
                    Check("Calls a tool", False, f"title was {type(call.get('title')).__name__}, not a string")
                )
            else:
                result.checks.append(Check("Calls a tool", True, f"title={call['title']!r}"))

            # 3. Streaming.
            deltas, stream_detail = await self._stream(client, target, extra)
            result.checks.append(
                Check("Streams", bool(deltas), stream_detail)
            )

            # 4. Multi-tool routing: the right tool, not merely a tool.
            data = await self._post(
                client,
                {
                    "model": target,
                    "messages": [{"role": "user", "content": _JOB_PROMPT}],
                    "tools": [_CANDIDATE_TOOL, _JD_TOOL],
                    "max_tokens": 256,
                    **extra,
                },
            )
            cost += _cost_of(data)
            names = _tool_names(data)
            if names == ["emit_job_description"]:
                result.checks.append(Check("Picks the right tool", True, "chose emit_job_description"))
            elif not names:
                result.checks.append(Check("Picks the right tool", False, "called no tool at all"))
            else:
                result.checks.append(Check("Picks the right tool", False, f"called {names}"))

        result.cost_usd = round(cost, 6)
        result.ok = all(c.ok for c in result.checks)
        if not result.ok:
            failed = [c.name for c in result.checks if not c.ok]
            result.warning = (
                f"{', '.join(failed)} failed. Binding a workload that streams AND sends "
                "tools to this model will stop it recording answers rather than degrade "
                "it, because emulated tools and streaming do not compose."
            )
        return result

    async def _stream(
        self, client: httpx.AsyncClient, target: str, extra: dict[str, Any]
    ) -> tuple[int, str]:
        body = {
            "model": target,
            "messages": [{"role": "user", "content": "Count from one to five, in words."}],
            "max_tokens": 64,
            "stream": True,
            **extra,
        }
        deltas = 0
        try:
            async with client.stream(
                "POST",
                f"{self._base}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json=body,
            ) as resp:
                if resp.status_code >= 400:
                    return 0, _explain(resp.status_code, await resp.aread())
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        parsed = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    for choice in parsed.get("choices") or []:
                        if (choice.get("delta") or {}).get("content"):
                            deltas += 1
        except httpx.HTTPError as exc:
            return 0, f"stream failed: {exc}"
        return deltas, f"{deltas} text chunks" if deltas else "no text chunks arrived"


def _cost_of(data: dict[str, Any]) -> float:
    usage = data.get("usage") or {}
    try:
        return float(usage.get("cost") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _tool_names(data: dict[str, Any]) -> list[str]:
    calls = (data.get("choices") or [{}])[0].get("message", {}).get("tool_calls") or []
    return [c.get("function", {}).get("name", "") for c in calls]


def _first_tool_call(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    calls = (data.get("choices") or [{}])[0].get("message", {}).get("tool_calls") or []
    for call in calls:
        fn = call.get("function") or {}
        if fn.get("name") != name:
            continue
        raw = fn.get("arguments")
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return None


def _explain(status: int, body: object) -> str:
    """Turn a gateway error into something a person can act on.

    401 in particular: the most likely cause is the failure that prompted this
    whole feature — a key from one provider sitting in another's field.
    """
    text = body.decode() if isinstance(body, bytes) else str(body)
    snippet = text[:300]
    if status == 401:
        return (
            "The provider rejected the key (401). Check that the key belongs to this "
            f"provider — a key from a different provider fails exactly like this. {snippet}"
        )
    if "no healthy deployments" in text.lower():
        # litellm's phrasing for "I have never heard of this model", which reads
        # like an outage. It is almost always a provider that was saved but whose
        # gateway restart has not finished, or a model id with a typo.
        return (
            "The gateway has no route for this model. Either the provider was saved "
            "but the gateway has not finished restarting — wait a few seconds and try "
            "again — or the model id is misspelled."
        )
    if status == 404:
        return f"The gateway does not know this model id (404). Check the spelling. {snippet}"
    if status == 402:
        return f"The provider reports no credit left (402). {snippet}"
    return f"The gateway returned {status}. {snippet}"
