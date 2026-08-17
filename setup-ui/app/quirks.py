"""Per-model compatibility settings, derived from catalogue metadata.

WHY THIS IS NOT OPTIONAL. Two measured failures, both silent:

1. REASONING MODELS RETURN EMPTY STRINGS. A reasoning model spends `max_tokens`
   on hidden reasoning BEFORE it emits any content, so a call site asking for 64
   tokens gets `finish_reason: length` and `text: ''`. Measured on z-ai/glm-5.2:
   77 reasoning tokens before 3 of content. It fires STOCHASTICALLY — the same
   prompt returned 'ready' six times in a row by hand and then failed the test
   suite — which is how it would survive setup and break in production.

2. GPT-5 MODELS REJECT temperature=0, with
     400 "Unsupported value: 'temperature' does not support 0 with this model."
   Nine call sites in this repo send it (candidate_detection, end_state,
   coverage_tracker, both worker llm clients, feedback-agent's api server,
   parse_jd, synthesize). THREE fixes that do not work, each tried against the
   running proxy before `additional_drop_params` was found — do not "simplify"
   this into any of them:
     * `litellm_settings.drop_params: true`, which is already set globally. It
       drops params a provider does not SUPPORT; openai supports temperature, so
       it is the VALUE that is rejected and drop_params never considers it.
     * `litellm_params: {temperature: 1}`. Those are DEFAULTS — an explicit
       temperature=0 in the request overrides them and the 400 survives.
     * `model_info: {supported_openai_params: [...]}`. Not honoured for dropping
       on this path either; the 400 survives unchanged.
   `additional_drop_params` removes the named params for one deployment before
   the request leaves the proxy. The determinism those call sites ask for with 0
   is not lost, it is unavailable on these models at all; anthropic and ollama
   still honour temperature=0 normally.

   litellm-config.yaml carried this for a single smoke alias. Once a user can
   point EVERY workload at OpenAI it has to apply to every generated entry,
   which is why it is unconditional for the provider below rather than attached
   to one model id.

DERIVED, NEVER TYPED BY HAND. OpenRouter publishes `supported_parameters` and a
`reasoning` object per model, so the answer is a lookup rather than a guess.
Hand-maintaining quirks for 400+ models is not a thing anyone would keep up.

PREFER A LOW EFFORT TIER OVER DISABLING. Turning reasoning off entirely cost
qwen/qwen3.8-27b its multi-tool routing — 4 of 5 correct, one reply with no tool
call at all — where `effort: low` held 5 of 5. Disabling is the fallback for
models that publish no low tier (glm-5.2 offers only high and xhigh), and is
legal only because those models report `mandatory: false`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.providers import ProviderSpec

#: Cheapest first. A model's lowest published effort is the one we ask for.
_EFFORT_ORDER = ("low", "medium", "high", "xhigh")

#: Efforts cheap enough that reasoning stays on. Above these the token cost is
#: what caused the empty replies in the first place, so we disable instead.
_CHEAP_EFFORTS = ("low", "medium")


@dataclass(frozen=True)
class ModelQuirks:
    """What to add to one generated `litellm_params` block, and why."""

    params: dict[str, Any] = field(default_factory=dict)
    supports_tools: bool = True
    #: Human-readable, shown in the UI beside the model. Empty when nothing is odd.
    notes: tuple[str, ...] = ()
    #: Set when the model cannot be made safe by configuration alone.
    warning: str = ""


def _lowest_effort(efforts: list[str]) -> str | None:
    for candidate in _EFFORT_ORDER:
        if candidate in efforts:
            return candidate
    return None


def derive(
    spec: ProviderSpec, model_id: str, metadata: dict[str, Any] | None = None
) -> ModelQuirks:
    """Compatibility settings for one provider/model pair.

    `metadata` is one entry from the provider's catalogue, or None when the
    provider publishes none. Absent metadata falls back to the provider-level
    constant rather than guessing per model.
    """
    params: dict[str, Any] = {}
    notes: list[str] = []
    warning = ""

    if spec.id == "openai":
        # Unconditional: this repo cannot know whether a given OpenAI model id is
        # a reasoning model, and dropping an unsupported temperature is harmless
        # on models that would have accepted it.
        params["additional_drop_params"] = ["temperature"]
        notes.append("temperature is dropped; GPT-5 models accept only the default")

    supports_tools = spec.supports_tools if spec.supports_tools is not None else True

    if metadata:
        parameters = metadata.get("supported_parameters") or []
        if parameters:
            supports_tools = "tools" in parameters

        reasoning = metadata.get("reasoning") or {}
        if isinstance(reasoning, dict) and reasoning.get("default_enabled"):
            efforts = [e for e in (reasoning.get("supported_efforts") or []) if isinstance(e, str)]
            lowest = _lowest_effort(efforts)
            mandatory = bool(reasoning.get("mandatory"))

            if lowest in _CHEAP_EFFORTS:
                params["reasoning"] = {"effort": lowest}
                notes.append(f"reasoning pinned to {lowest} effort")
            elif mandatory:
                # Cannot be turned off, and its cheapest tier is expensive. Left
                # ON deliberately: a wrong `enabled: false` on a mandatory model
                # is rejected by the provider, and silently degrading it would
                # reintroduce the empty-reply failure this module exists to stop.
                if lowest:
                    params["reasoning"] = {"effort": lowest}
                warning = (
                    "This model always reasons and offers no cheap effort tier, so it "
                    "spends part of every max_tokens budget before answering. Short "
                    "replies may come back empty."
                )
                notes.append("reasoning is mandatory on this model")
            else:
                params["reasoning"] = {"enabled": False}
                notes.append("reasoning disabled; this model offers no low effort tier")

    if not supports_tools:
        notes.append("no native tool calling; tools are emulated in the prompt")

    return ModelQuirks(
        params=params,
        supports_tools=supports_tools,
        notes=tuple(notes),
        warning=warning,
    )
