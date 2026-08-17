"""Which model providers exist, what each one needs, and what the user chose.

THE POINT OF THIS FILE. Before it, `litellm-config.yaml` hardcoded
`anthropic/claude-sonnet-5` and `os.environ/ANTHROPIC_API_KEY` in 23 of its 27
aliases, and the setup UI offered exactly two key fields. A self-hoster with an
OpenRouter key had nowhere to put it — so one put it in the Anthropic field,
readiness reported Core: live because it only checks that the value is
non-empty, litellm booted healthy because its healthcheck is pure liveness, and
every call then 401'd against api.anthropic.com at request time. Three green
lights over a dead stack. This module is the missing concept those three
surfaces were each guessing at: a PROVIDER, which has a key, a preferred model,
and quirks.

TWO MODEL SLOTS, NOT ONE. `preferred` and `fast`. litellm-config.yaml's header
forbids collapsing tiers onto one model because it silently re-prices and
re-times a workload; five aliases run the cheap tier today and seventeen run the
standard one. One slot per provider would have quietly moved all five onto the
expensive model the first time someone switched provider. `fast` falls back to
`preferred` when blank, so the simple case stays one field.

SECRETS ARE NOT HERE. The registry holds provider ids and model ids only. Keys
stay in `.env`, which is read by the litellm container alone — that is the
property that makes the gateway the single egress point, and it survives this
change intact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class RegistryError(Exception):
    """The registry could not be read or a change to it was rejected. Safe to show."""


@dataclass(frozen=True)
class ProviderSpec:
    """Everything about a provider that does not depend on the user's choices."""

    id: str
    label: str
    #: LiteLLM's provider prefix. The model string it is given is
    #: f"{prefix}/{model_id}", which is the whole of what makes a workload
    #: repointable without an application rebuild.
    prefix: str
    #: The `.env` variable holding the credential, or None for a provider that
    #: needs none. Ollama is local and unauthenticated, and inventing an empty
    #: key field for it would imply an account is required to self-host.
    key_var: str | None
    #: Providers reached at an address rather than by credential.
    base_var: str | None
    default_preferred: str
    default_fast: str
    #: Where per-model capability metadata comes from. Only OpenRouter publishes
    #: it; for the rest, capability is a known constant (see supports_tools).
    catalogue_url: str | None = None
    #: Whether models from this provider do native function calling. Used when no
    #: catalogue can answer. `None` means "unknown, ask the catalogue".
    supports_tools: bool | None = None


#: Ordered: this is the order the provider dropdown renders in.
PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        id="anthropic",
        label="Anthropic",
        prefix="anthropic",
        key_var="ANTHROPIC_API_KEY",
        base_var=None,
        default_preferred="claude-sonnet-5",
        default_fast="claude-haiku-4-5-20251001",
        supports_tools=True,
    ),
    "openai": ProviderSpec(
        id="openai",
        label="OpenAI",
        prefix="openai",
        key_var="OPENAI_API_KEY",
        base_var=None,
        default_preferred="gpt-5.6-terra",
        default_fast="gpt-5.6-terra",
        supports_tools=True,
    ),
    "openrouter": ProviderSpec(
        id="openrouter",
        label="OpenRouter",
        prefix="openrouter",
        key_var="OPENROUTER_API_KEY",
        base_var=None,
        # Deliberately a model measured to need NO quirk (see litellm-config.yaml's
        # spike table): reasoning is off by default on it, so a first run cannot
        # land on the empty-reply failure before the user has read anything.
        default_preferred="deepseek/deepseek-v4-flash",
        default_fast="deepseek/deepseek-v4-flash",
        catalogue_url="https://openrouter.ai/api/v1/models",
        supports_tools=None,
    ),
    "ollama": ProviderSpec(
        id="ollama",
        label="Ollama (local)",
        prefix="ollama_chat",
        key_var=None,
        base_var="OLLAMA_API_BASE",
        default_preferred="gemma4:latest",
        default_fast="gemma4:latest",
        # Local models rarely do native function calling, and declaring `true`
        # wrongly is the silent failure: llm-core falls back to prompt-emulated
        # JSON tools, which do not compose with streaming at all.
        supports_tools=False,
    ),
}


@dataclass
class ProviderEntry:
    """One configured provider: which models it serves for each tier."""

    preferred: str
    fast: str = ""

    def fast_or_preferred(self) -> str:
        return self.fast.strip() or self.preferred


@dataclass
class Registry:
    """The user's model configuration.

    `default` names the provider every workload uses unless `overrides` says
    otherwise — "whatever they mark as preferred becomes pre-configured for all
    their downstream prompts".
    """

    default: str
    providers: dict[str, ProviderEntry] = field(default_factory=dict)
    #: alias -> {"provider": str, "model": str}. The per-workload escape hatch.
    overrides: dict[str, dict[str, str]] = field(default_factory=dict)

    def entry(self, provider_id: str) -> ProviderEntry:
        try:
            return self.providers[provider_id]
        except KeyError:
            raise RegistryError(f"Provider '{provider_id}' is not configured.") from None

    def resolve(self, alias: str, tier: str) -> tuple[ProviderSpec, str]:
        """The provider and model id an alias should be generated against.

        An override wins; otherwise the default provider's slot for this tier.
        """
        override = self.overrides.get(alias)
        if override:
            spec = PROVIDERS.get(override.get("provider", ""))
            if spec is None:
                raise RegistryError(
                    f"Override for '{alias}' names unknown provider "
                    f"'{override.get('provider')}'."
                )
            model = override.get("model", "").strip()
            if not model:
                raise RegistryError(f"Override for '{alias}' has no model.")
            return spec, model

        spec = PROVIDERS.get(self.default)
        if spec is None:
            raise RegistryError(f"Default provider '{self.default}' is not a known provider.")
        entry = self.entry(self.default)
        model = entry.fast_or_preferred() if tier == "fast" else entry.preferred
        if not model.strip():
            raise RegistryError(f"Provider '{self.default}' has no model set.")
        return spec, model.strip()


#: What a deployment that has never opened this UI gets. Chosen to regenerate
#: byte-equivalent aliases to the hand-written config this replaced — see
#: tests/test_litellm_gen.py, which fails if any of the 27 drifts. A fresh clone
#: must behave EXACTLY as it did before this feature existed.
DEFAULT_REGISTRY = Registry(
    default="anthropic",
    providers={
        "anthropic": ProviderEntry(
            preferred="claude-sonnet-5", fast="claude-haiku-4-5-20251001"
        ),
        "openai": ProviderEntry(preferred="gpt-5.6-terra"),
        "ollama": ProviderEntry(preferred="gemma4:latest"),
    },
)


def load(path: Path) -> Registry:
    """The registry, or the built-in default when the file is absent.

    Absent is the NORMAL state, not an error: the defaults reproduce the
    behaviour every existing deployment already has, so this feature costs a
    fresh clone nothing until someone opens the page.
    """
    if not path.exists():
        return DEFAULT_REGISTRY
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RegistryError(f"Could not read {path.name}: {exc}") from exc
    return from_dict(raw)


def from_dict(raw: dict[str, Any]) -> Registry:
    providers: dict[str, ProviderEntry] = {}
    for pid, entry in (raw.get("providers") or {}).items():
        if pid not in PROVIDERS:
            raise RegistryError(f"Unknown provider '{pid}'.")
        if not isinstance(entry, dict):
            raise RegistryError(f"Provider '{pid}' is not an object.")
        preferred = str(entry.get("preferred", "")).strip()
        if not preferred:
            raise RegistryError(f"Provider '{pid}' has no preferred model.")
        providers[pid] = ProviderEntry(preferred=preferred, fast=str(entry.get("fast", "")).strip())

    default = str(raw.get("default", "")).strip()
    if not default:
        raise RegistryError("No default provider is set.")
    if default not in providers:
        raise RegistryError(f"Default provider '{default}' is not in the provider list.")

    overrides: dict[str, dict[str, str]] = {}
    for alias, ov in (raw.get("overrides") or {}).items():
        if not isinstance(ov, dict):
            raise RegistryError(f"Override for '{alias}' is not an object.")
        pid = str(ov.get("provider", "")).strip()
        model = str(ov.get("model", "")).strip()
        if pid not in providers:
            raise RegistryError(
                f"Override for '{alias}' names provider '{pid}', which is not configured."
            )
        if not model:
            raise RegistryError(f"Override for '{alias}' has no model.")
        overrides[alias] = {"provider": pid, "model": model}

    return Registry(default=default, providers=providers, overrides=overrides)


def to_dict(registry: Registry) -> dict[str, Any]:
    return {
        "default": registry.default,
        "providers": {
            pid: ({"preferred": e.preferred, "fast": e.fast} if e.fast else {"preferred": e.preferred})
            for pid, e in registry.providers.items()
        },
        "overrides": registry.overrides,
    }


def required_env(registry: Registry) -> dict[str, str]:
    """Which `.env` variables the configured providers need, and why.

    Returned rather than checked here: this module knows nothing about `.env`,
    and the readiness panel is what turns "OPENROUTER_API_KEY is empty" into a
    sentence a person can act on.
    """
    needed: dict[str, str] = {}
    for pid in registry.providers:
        spec = PROVIDERS[pid]
        if spec.key_var:
            needed[spec.key_var] = f"{spec.label} API key"
        if spec.base_var:
            needed[spec.base_var] = f"{spec.label} base URL"
    return needed
