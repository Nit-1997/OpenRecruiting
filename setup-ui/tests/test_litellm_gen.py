"""The generator must reproduce the hand-written config it replaced.

THIS IS THE SAFETY NET FOR A RISKY CHANGE. `litellm-config.yaml` was tuned by
hand over several debugging sessions, and replacing it with generated output is
only defensible if the default output is provably the same configuration. GOLDEN
below is that file's 27 aliases, extracted from git before the change. If a
refactor of the workload table or the quirk rules moves any alias onto a
different model or flips a capability flag, this fails with the alias name.

A fresh clone has no llm-providers.json, so DEFAULT_REGISTRY is what it runs.
That makes this test the guarantee that installing this feature changes nothing
until someone opens the page and chooses something.
"""

from __future__ import annotations

import pytest
import yaml

from app.litellm_gen import render
from app.providers import DEFAULT_REGISTRY, ProviderEntry, Registry
from app.quirks import derive
from app.providers import PROVIDERS


#: Every alias of the pre-generator litellm-config.yaml, verbatim.
GOLDEN: dict[str, dict] = {
    "intake-jd": {"model": "anthropic/claude-haiku-4-5-20251001", "tools": True},
    "intake-jd-local": {"model": "ollama_chat/gemma4:latest", "tools": False},
    "debrief-chat": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "intake-text": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "context-parse-jd": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "screening-generator": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "screening-assessor": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "persona-reduce": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "route-intent": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "signal-extract": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "resume-extract": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "candidate-detect": {"model": "anthropic/claude-haiku-4-5-20251001", "tools": True},
    "parse-role-intent": {"model": "anthropic/claude-haiku-4-5-20251001", "tools": True},
    "end-state": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "voice-intake": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "voice-screening": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "voice-feedback": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "feedback-condense": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "context-synthesize": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "feedback-haiku": {"model": "anthropic/claude-haiku-4-5-20251001", "tools": True},
    "feedback-sonnet": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "intake-agent-haiku": {"model": "anthropic/claude-haiku-4-5-20251001", "tools": True},
    "intake-agent-sonnet": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "smoke-anthropic": {"model": "anthropic/claude-sonnet-5", "tools": True},
    "smoke-openai": {
        "model": "openai/gpt-5.6-terra",
        "tools": True,
        "drop": ["temperature"],
    },
    "smoke-local": {"model": "ollama_chat/gemma4:latest", "tools": False},
    "gemma-local": {"model": "ollama_chat/gemma4:latest", "tools": False},
}


def _entries(text: str) -> dict[str, dict]:
    """Parsed model_list, keyed by alias. Wildcard routes excluded."""
    parsed = yaml.safe_load(text)
    return {
        m["model_name"]: m
        for m in parsed["model_list"]
        if not m["model_name"].endswith("/*")
    }


def test_the_generated_output_is_valid_yaml_with_the_expected_sections():
    parsed = yaml.safe_load(render(DEFAULT_REGISTRY))
    assert "model_list" in parsed
    assert parsed["litellm_settings"]["drop_params"] is True
    assert parsed["general_settings"]["master_key"] == "os.environ/LITELLM_MASTER_KEY"


def test_the_default_registry_reproduces_every_alias_of_the_replaced_file():
    entries = _entries(render(DEFAULT_REGISTRY))
    assert set(entries) == set(GOLDEN), (
        "the generated alias set differs from the hand-written file it replaced; "
        f"missing={sorted(set(GOLDEN) - set(entries))} "
        f"added={sorted(set(entries) - set(GOLDEN))}"
    )


@pytest.mark.parametrize("alias", sorted(GOLDEN))
def test_each_alias_resolves_to_the_model_it_did_before(alias: str):
    entry = _entries(render(DEFAULT_REGISTRY))[alias]
    expected = GOLDEN[alias]
    params = entry["litellm_params"]

    assert params["model"] == expected["model"], (
        f"{alias} moved from {expected['model']} to {params['model']} — this "
        "re-prices and re-times the workload, which litellm-config.yaml's header "
        "forbids doing silently"
    )
    assert entry["model_info"]["supports_function_calling"] is expected["tools"]
    if "drop" in expected:
        assert params["additional_drop_params"] == expected["drop"]
    else:
        assert "additional_drop_params" not in params


def test_the_five_cheap_tier_aliases_are_exactly_the_ones_measured():
    """The old file's header said three. It was stale; counting the entries gave
    five. Pinned here so the table cannot drift back to the header's claim."""
    entries = _entries(render(DEFAULT_REGISTRY))
    cheap = {
        name
        for name, e in entries.items()
        if e["litellm_params"]["model"] == "anthropic/claude-haiku-4-5-20251001"
    }
    assert cheap == {
        "intake-jd",
        "candidate-detect",
        "parse-role-intent",
        "feedback-haiku",
        "intake-agent-haiku",
    }


def test_no_alias_is_emitted_twice():
    """A duplicate model_name is a load-balancing group, not an override — requests
    would round-robin between two models with nothing reporting it."""
    text = render(DEFAULT_REGISTRY)
    names = [m["model_name"] for m in yaml.safe_load(text)["model_list"]]
    assert len(names) == len(set(names)), f"duplicates: {sorted({n for n in names if names.count(n) > 1})}"


def test_every_configured_provider_gets_a_wildcard_route_for_the_probe():
    parsed = yaml.safe_load(render(DEFAULT_REGISTRY))
    wildcards = {m["model_name"] for m in parsed["model_list"] if m["model_name"].endswith("/*")}
    assert wildcards == {"anthropic/*", "openai/*", "ollama_chat/*"}


# ── switching provider ──────────────────────────────────────────────────────


def _openrouter_registry() -> Registry:
    return Registry(
        default="openrouter",
        providers={
            "openrouter": ProviderEntry(
                preferred="z-ai/glm-5.2", fast="deepseek/deepseek-v4-flash"
            )
        },
    )


def test_switching_the_default_provider_moves_every_workload_but_keeps_the_tiers():
    entries = _entries(render(_openrouter_registry()))
    assert entries["debrief-chat"]["litellm_params"]["model"] == "openrouter/z-ai/glm-5.2"
    assert (
        entries["intake-jd"]["litellm_params"]["model"]
        == "openrouter/deepseek/deepseek-v4-flash"
    ), "the cheap tier must follow the fast slot, not collapse onto preferred"
    assert entries["debrief-chat"]["litellm_params"]["api_key"] == "os.environ/OPENROUTER_API_KEY"


def test_a_blank_fast_slot_falls_back_to_preferred():
    registry = Registry(
        default="openrouter",
        providers={"openrouter": ProviderEntry(preferred="z-ai/glm-5.2")},
    )
    entries = _entries(render(registry))
    assert entries["intake-jd"]["litellm_params"]["model"] == "openrouter/z-ai/glm-5.2"


def test_a_per_workload_override_wins_over_the_default_provider():
    registry = _openrouter_registry()
    registry.providers["anthropic"] = ProviderEntry(preferred="claude-sonnet-5")
    registry.overrides["screening-assessor"] = {
        "provider": "anthropic",
        "model": "claude-sonnet-5",
    }
    entries = _entries(render(registry))
    assert entries["screening-assessor"]["litellm_params"]["model"] == "anthropic/claude-sonnet-5"
    assert entries["screening-assessor"]["litellm_params"]["api_key"] == "os.environ/ANTHROPIC_API_KEY"
    # The override must not leak into its neighbours.
    assert entries["screening-generator"]["litellm_params"]["model"] == "openrouter/z-ai/glm-5.2"


def test_local_aliases_stay_on_ollama_when_the_default_provider_is_not_ollama():
    registry = _openrouter_registry()
    registry.providers["ollama"] = ProviderEntry(preferred="gemma4:latest")
    entries = _entries(render(registry))
    assert entries["intake-jd-local"]["litellm_params"]["model"] == "ollama_chat/gemma4:latest"
    assert entries["gemma-local"]["litellm_params"]["model"] == "ollama_chat/gemma4:latest"


# ── quirks reach the generated file ─────────────────────────────────────────


def test_a_reasoning_model_gets_its_quirk_written_into_every_alias():
    """The spike's finding, end to end: without this the model returns empty
    strings whenever a call site asks for a small max_tokens."""
    catalogue = {
        "openrouter/z-ai/glm-5.2": {
            "supported_parameters": ["tools", "temperature"],
            "reasoning": {"default_enabled": True, "supported_efforts": ["xhigh", "high"]},
        }
    }
    entries = _entries(render(_openrouter_registry(), catalogue))
    assert entries["debrief-chat"]["litellm_params"]["reasoning"] == {"enabled": False}


def test_a_model_with_a_low_effort_tier_is_pinned_low_rather_than_disabled():
    """Measured: disabling reasoning outright cost qwen3.8-27b its multi-tool
    routing, where effort:low held."""
    registry = Registry(
        default="openrouter",
        providers={"openrouter": ProviderEntry(preferred="qwen/qwen3.8-27b")},
    )
    catalogue = {
        "openrouter/qwen/qwen3.8-27b": {
            "supported_parameters": ["tools"],
            "reasoning": {
                "default_enabled": True,
                "supported_efforts": ["xhigh", "medium", "low"],
            },
        }
    }
    entries = _entries(render(registry, catalogue))
    assert entries["debrief-chat"]["litellm_params"]["reasoning"] == {"effort": "low"}


def test_a_model_without_tools_in_the_catalogue_is_declared_incapable():
    registry = Registry(
        default="openrouter",
        providers={"openrouter": ProviderEntry(preferred="tencent/hy3")},
    )
    catalogue = {"openrouter/tencent/hy3": {"supported_parameters": ["temperature"]}}
    entries = _entries(render(registry, catalogue))
    assert entries["debrief-chat"]["model_info"]["supports_function_calling"] is False


def test_an_absent_catalogue_falls_back_to_the_provider_constant():
    """No network, no metadata: an OpenRouter model must not be assumed capable
    on the strength of nothing. It falls back to the provider default rather than
    inventing a per-model answer."""
    quirks = derive(PROVIDERS["openrouter"], "some/unknown-model", None)
    assert quirks.params == {}
    assert quirks.supports_tools is True


def test_openai_always_drops_temperature():
    """Nine call sites send temperature=0 and GPT-5 models reject the value.

    Scoped to the openai-backed aliases: the `-local` ones stay on Ollama by
    design, and Ollama honours temperature=0 normally. Asserting over every entry
    would demand the quirk on models that must not have it.
    """
    registry = Registry(
        default="openai", providers={"openai": ProviderEntry(preferred="gpt-5.6-terra")}
    )
    entries = _entries(render(registry))
    openai_aliases = {
        alias: e
        for alias, e in entries.items()
        if e["litellm_params"]["model"].startswith("openai/")
    }
    assert len(openai_aliases) == 23, "expected every workload plus the smoke alias"
    for alias, entry in openai_aliases.items():
        assert entry["litellm_params"]["additional_drop_params"] == ["temperature"], alias

    for alias, entry in entries.items():
        if entry["litellm_params"]["model"].startswith("ollama_chat/"):
            assert "additional_drop_params" not in entry["litellm_params"], alias


def test_a_mandatory_reasoning_model_is_flagged_rather_than_silently_disabled():
    metadata = {
        "supported_parameters": ["tools"],
        "reasoning": {
            "default_enabled": True,
            "mandatory": True,
            "supported_efforts": ["xhigh", "high"],
        },
    }
    quirks = derive(PROVIDERS["openrouter"], "some/thinker", metadata)
    assert quirks.params["reasoning"] == {"effort": "high"}
    assert quirks.warning, "a model that cannot stop reasoning must warn the user"
