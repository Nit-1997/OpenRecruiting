"""Render `litellm-config.yaml` from the workload table and the user's registry.

WHY GENERATE A FILE THAT USED TO BE HAND-WRITTEN. Three things have to vary per
alias once a user can choose their provider, and none of them can be expressed
by an env reference in a static file:

  * the model string differs per alias, because tiers and per-workload overrides
    both exist — one `os.environ/LLM_MODEL` would collapse all 27 onto one model;
  * `additional_drop_params` applies to OpenAI and nothing else;
  * `model_info.supports_function_calling` is a per-MODEL fact read from a
    catalogue, not a per-file constant.

The old `set_model` rewrote a single `model:` line and left `api_key` pointing at
the previous provider. That is not a small bug: it is exactly how a user's
OpenRouter key ended up being sent to api.anthropic.com while every status
surface read green. Generating the whole entry means the key, the model and the
quirks can never disagree.

TEXT, NOT yaml.dump. The comments are the point — several are the only surviving
record of why a workload sits on the tier it does — and a dumper would drop every
one of them.
"""

from __future__ import annotations

from typing import Any

from app.providers import PROVIDERS, ProviderSpec, Registry
from app.quirks import ModelQuirks, derive
from app.workloads import LOCAL_EXTRAS, SMOKE_ALIAS_NAMES, WORKLOADS, Workload

_HEADER = """\
# Alias -> provider map for the LiteLLM gateway.
#
# GENERATED FILE — edit through the setup UI, not by hand. It is rendered from
# setup-ui/app/workloads.py (what each alias is for and which tier it must stay
# on) and llm-providers.json (which provider and model you chose). Hand edits
# survive until the next save from that page and then vanish, which is worse than
# not being allowed at all — so change the source, not the output.
#
# Applications only ever send an alias. That is what lets a workload move between
# providers with no application rebuild, and it is why no service in this repo
# holds a provider credential: this file names them, the gateway resolves them,
# and the gateway is the only process that egresses.
#
# IMPORTANT: two entries sharing a model_name is NOT an override, it declares a
# load-balancing group and requests round-robin between them. The generator
# refuses to emit a duplicate for that reason.
#
# MODEL TIER IS PART OF THE CONTRACT. An alias must resolve to the same tier the
# call site uses today, or a save silently re-prices and re-times a workload while
# claiming to be a no-op. Five aliases run the cheap tier and seventeen run the
# standard one; workloads.py records which is which and why.
"""

_FOOTER = """\
litellm_settings:
  drop_params: true        # silently drop params a provider does not accept
  num_retries: 2
  request_timeout: 120

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
"""

_WILDCARD_NOTE = """\
  # --- Wildcard routes: how "test this model" reaches an unconfigured model ---
  # Without these, probing a model you have not saved yet would mean writing it
  # into this file and restarting the gateway — a 30-second round trip for a
  # button. With them, any model of a CONFIGURED provider is reachable by its
  # full id, so the setup UI can measure a candidate before you commit to it.
  #
  # This does NOT widen who holds a credential: the key still lives only in this
  # container, and the caller supplies a model name, never a key. It does widen
  # what a caller holding the gateway master key can spend money on, from the
  # alias list to that provider's whole catalogue. Accepted because the master
  # key is already shared by every application service, and because the
  # alternative is a setup UI that cannot answer "will this model work?".
"""


def _indent_comment(text: str, indent: str = "  ") -> list[str]:
    return [f"{indent}# {line}".rstrip() for line in text.split("\n")]


def _render_params(spec: ProviderSpec, model_id: str, quirks: ModelQuirks) -> list[str]:
    lines = [f"      model: {spec.prefix}/{model_id}"]
    if spec.key_var:
        lines.append(f"      api_key: os.environ/{spec.key_var}")
    if spec.base_var:
        lines.append(f"      api_base: os.environ/{spec.base_var}")
    for key, value in quirks.params.items():
        lines.append(f"      {key}: {_scalar(value)}")
    return lines


def _scalar(value: Any) -> str:
    """Flow-style rendering, matching the file this replaced.

    Deliberately narrow: it handles the shapes quirks actually produce and raises
    on anything else, so a new quirk shape fails here rather than emitting YAML
    that parses into something unintended.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "[" + ", ".join(f'"{v}"' for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_scalar(v)}" for k, v in value.items()) + "}"
    raise TypeError(f"litellm_gen cannot render {type(value).__name__}: {value!r}")


def _render_entry(
    name: str,
    spec: ProviderSpec,
    model_id: str,
    quirks: ModelQuirks,
    workload: Workload | None,
) -> list[str]:
    lines: list[str] = []
    if workload and workload.section:
        lines.append(f"  # ── {workload.section.splitlines()[0]} " + "─" * 20)
        rest = workload.section.split("\n", 1)
        if len(rest) > 1:
            lines.extend(_indent_comment(rest[1]))
        lines.append("")
    if workload and workload.comment:
        lines.extend(_indent_comment(workload.comment))
    lines.append(f"  - model_name: {name}")
    lines.append("    litellm_params:")
    lines.extend(_render_params(spec, model_id, quirks))
    lines.append(
        f"    model_info: {{supports_function_calling: {_scalar(quirks.supports_tools)}}}"
    )
    lines.append("")
    return lines


def render(registry: Registry, catalogue: dict[str, dict[str, Any]] | None = None) -> str:
    """The complete `litellm-config.yaml` for this registry.

    `catalogue` maps a provider-qualified model id to its metadata, used to derive
    capability and reasoning quirks. None means "no catalogue available", which
    falls back to the provider-level constants rather than guessing.
    """
    catalogue = catalogue or {}
    seen: set[str] = set()
    lines: list[str] = [_HEADER, "model_list:"]

    def emit(name: str, spec: ProviderSpec, model_id: str, workload: Workload | None) -> None:
        if name in seen:
            # A duplicate model_name is a load-balancing group, not an override.
            # Refusing here is the difference between a clear error and requests
            # silently round-robinning between two models.
            raise ValueError(f"duplicate alias '{name}' — would become a load-balancing group")
        seen.add(name)
        quirks = derive(spec, model_id, catalogue.get(f"{spec.id}/{model_id}"))
        lines.extend(_render_entry(name, spec, model_id, quirks, workload))

    ollama = PROVIDERS["ollama"]

    for workload in WORKLOADS:
        if workload.tier == "local":
            entry = registry.providers.get("ollama")
            model_id = entry.preferred if entry else ollama.default_preferred
            emit(workload.name, ollama, model_id, workload)
            continue
        spec, model_id = registry.resolve(workload.name, workload.tier)
        emit(workload.name, spec, model_id, workload)

    lines.append("  # --- Smoke aliases: one per configured provider, for the live suite ---")
    lines.append("")
    for provider_id in registry.providers:
        alias = SMOKE_ALIAS_NAMES.get(provider_id)
        if not alias:
            continue
        spec = PROVIDERS[provider_id]
        emit(alias, spec, registry.entry(provider_id).preferred, None)

    for workload in LOCAL_EXTRAS:
        entry = registry.providers.get("ollama")
        model_id = entry.preferred if entry else ollama.default_preferred
        emit(workload.name, ollama, model_id, workload)

    lines.append(_WILDCARD_NOTE)
    for provider_id in registry.providers:
        spec = PROVIDERS[provider_id]
        lines.append(f"  - model_name: {spec.prefix}/*")
        lines.append("    litellm_params:")
        lines.append(f"      model: {spec.prefix}/*")
        if spec.key_var:
            lines.append(f"      api_key: os.environ/{spec.key_var}")
        if spec.base_var:
            lines.append(f"      api_base: os.environ/{spec.base_var}")
        # PROVIDER-level quirks apply here too. A wildcard is a real deployment:
        # `openai/*` without additional_drop_params 400s on every one of this
        # repo's nine temperature=0 call sites, and the probe that rides this
        # route would report a perfectly good model as broken. Caught by
        # backend/tests/services/intake/test_llm_stream.py, which had already
        # predicted "the day someone adds a second openai deployment and forgets".
        #
        # Model-level quirks (reasoning) deliberately do NOT appear: a wildcard
        # serves every model of the provider and they differ per model. The
        # caller passes those per request — see app/probe.py.
        for key, value in derive(spec, "*", None).params.items():
            lines.append(f"      {key}: {_scalar(value)}")
        lines.append("")

    lines.append(_FOOTER)
    return "\n".join(lines)
