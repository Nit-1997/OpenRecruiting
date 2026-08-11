"""Editing litellm-config.yaml must not destroy its comments.

The comments in that file are the only record of why an alias is pinned to a
tier, which aliases send tools, and why the OpenAI deployment drops temperature.
A yaml round-trip would delete all of it, so writing is line-based and this
asserts the byte-level guarantee.
"""

from pathlib import Path

import pytest

from app.litellm_cfg import read_aliases, set_model

REPO = Path(__file__).resolve().parents[2]

SAMPLE = """\
model_list:
  # Haiku today: the cheap extraction path.
  - model_name: intake-jd
    litellm_params:
      model: anthropic/claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  # ── The three realtime voice pipelines ──────────────────
  # SENDS TOOLS. An alias without native function calling disables intake.
  - model_name: voice-intake
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}

  - model_name: smoke-openai
    litellm_params:
      model: openai/gpt-5.6-terra
      api_key: os.environ/OPENAI_API_KEY
      additional_drop_params: ["temperature"]
    model_info: {supports_function_calling: true}
"""


def test_every_alias_is_read_with_its_provider_and_capabilities():
    by_name = {a.name: a for a in read_aliases(SAMPLE)}

    assert set(by_name) == {"intake-jd", "voice-intake", "smoke-openai"}
    assert by_name["intake-jd"].provider == "anthropic"
    assert by_name["smoke-openai"].provider == "openai"
    assert by_name["voice-intake"].supports_tools is True


def test_the_temperature_workaround_is_surfaced():
    """The UI must show this, because an OpenAI reasoning model without it 400s
    every one of the nine call sites that send temperature=0."""
    by_name = {a.name: a for a in read_aliases(SAMPLE)}

    assert by_name["smoke-openai"].drops_temperature is True
    assert by_name["voice-intake"].drops_temperature is False


def test_the_comment_above_an_alias_becomes_its_description():
    by_name = {a.name: a for a in read_aliases(SAMPLE)}

    assert "cheap extraction path" in by_name["intake-jd"].description
    assert "SENDS TOOLS" in by_name["voice-intake"].description
    # A divider rule is decoration, not prose, and must not leak in.
    assert "──" not in by_name["voice-intake"].description


def test_changing_a_model_touches_exactly_one_line():
    out = set_model(SAMPLE, "voice-intake", "ollama_chat/gemma4:latest")

    changed = [(a, b) for a, b in zip(SAMPLE.splitlines(), out.splitlines()) if a != b]
    assert changed == [
        ("      model: anthropic/claude-sonnet-5", "      model: ollama_chat/gemma4:latest")
    ]


def test_every_comment_survives_a_change():
    out = set_model(SAMPLE, "intake-jd", "openai/gpt-5.6-terra")

    for line in SAMPLE.splitlines():
        if line.strip().startswith("#"):
            assert line in out, f"comment lost: {line}"


def test_editing_one_alias_never_touches_a_neighbour():
    """The model: line of the NEXT alias is the obvious thing a naive scan
    would hit when an alias is missing its own."""
    out = read_aliases(set_model(SAMPLE, "intake-jd", "openai/gpt-5.6-terra"))
    by_name = {a.name: a for a in out}

    assert by_name["intake-jd"].model == "openai/gpt-5.6-terra"
    assert by_name["voice-intake"].model == "anthropic/claude-sonnet-5"
    assert by_name["smoke-openai"].model == "openai/gpt-5.6-terra"  # unchanged, was already


def test_an_unknown_alias_raises_rather_than_appending():
    """A silently added alias would be served by the gateway and never
    noticed."""
    with pytest.raises(LookupError, match="No alias named"):
        set_model(SAMPLE, "not-an-alias", "anthropic/claude-sonnet-5")


def test_the_real_config_parses_and_round_trips_byte_identically():
    """Against the actual file, not a fixture — it has 27 aliases and far more
    comment shapes than any sample."""
    path = REPO / "litellm-config.yaml"
    if not path.exists():
        pytest.skip("litellm-config.yaml not reachable")
    text = path.read_text(encoding="utf-8")

    aliases = read_aliases(text)
    assert len(aliases) >= 25
    assert all(a.model for a in aliases)

    # Setting a model to its current value must be a no-op, byte for byte.
    target = aliases[0]
    assert set_model(text, target.name, target.model) == text
