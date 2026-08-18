"""Editing litellm-config.yaml must not destroy its comments.

The comments in that file are the only record of why an alias is pinned to a
tier, which aliases send tools, and why the OpenAI deployment drops temperature.
A yaml round-trip would delete all of it, so writing is line-based and this
asserts the byte-level guarantee.
"""

from pathlib import Path

import pytest

from app.litellm_cfg import read_aliases

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


def test_the_real_generated_config_parses():
    """Against the actual file, not a fixture — it has 27 aliases and far more
    comment shapes than any sample."""
    path = REPO / "litellm-config.yaml"
    if not path.exists():
        pytest.skip("litellm-config.yaml not reachable")
    text = path.read_text(encoding="utf-8")

    aliases = read_aliases(text)
    assert len(aliases) >= 25
    assert all(a.model for a in aliases)

    # Every alias the generator emits must be readable back, or the "Models per
    # task" list silently shows blanks for the ones it cannot parse.
    names = {a.name for a in aliases}
    assert "intake-jd" in names and "smoke-anthropic" in names
