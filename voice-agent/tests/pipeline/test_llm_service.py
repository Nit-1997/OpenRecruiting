"""What the pipeline factory hands its LLM service.

READ THIS BEFORE TRUSTING THIS FILE. Every conftest under voice-agent/tests
stubs pipecat into sys.modules, so OpenAILLMService here is a MagicMock. These
tests prove which kwargs THIS REPO passes and which modules it imports. They
prove NOTHING about whether pipecat accepts them, whether the gateway answers,
or whether a tool call survives the round trip — that is what
scripts/smoke_llm_service.py does, inside the built image against a live gateway.

The properties pinned here are the ones a wrong swap breaks silently.
"""
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

for _name in (
    "pipecat",
    "pipecat.services",
    "pipecat.services.openai",
    "pipecat.services.openai.llm",
    "pipecat.services.deepgram",
    "pipecat.services.deepgram.tts",
    "pipecat.services.deepgram.flux",
    "pipecat.services.deepgram.flux.stt",
):
    sys.modules.setdefault(_name, MagicMock())

from src.pipeline.services import create_llm  # noqa: E402

_SRC = Path(__file__).resolve().parents[2] / "src"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_the_service_is_built_against_a_gateway_base_url():
    """Observes GatewayLLMService, not OpenAILLMService.

    create_llm returns the subclass that restores the Anthropic adapter's
    message reshaping (see services.normalize_messages_for_gateway). Under this
    conftest OpenAILLMService is a MagicMock, so subclassing it makes
    GatewayLLMService a MagicMock too — the override is NOT real code here and
    nothing in this suite can exercise it. scripts/smoke_llm_service.py does,
    against real pipecat.
    """
    import src.pipeline.services as services

    create_llm(api_key="master-key", model="voice-intake", base_url="http://litellm:4000/v1")

    kwargs = services.GatewayLLMService.call_args.kwargs
    assert kwargs["base_url"] == "http://litellm:4000/v1"
    assert kwargs["model"] == "voice-intake"
    assert "anthropic" not in str(kwargs).lower()


def test_no_module_in_src_reads_a_provider_api_key():
    """Phase 7's whole point. voice-agent held the LAST provider credential in
    the repository; after this phase nothing outside the litellm proxy has one."""
    offenders = {
        p.relative_to(_SRC).as_posix()
        for p in _SRC.rglob("*.py")
        if "voice_anthropic_api_key" in p.read_text(encoding="utf-8")
        or "ANTHROPIC_API_KEY" in p.read_text(encoding="utf-8")
    }
    assert offenders == set()


def test_no_module_in_src_imports_a_provider_llm_service():
    offenders = {
        p.relative_to(_SRC).as_posix()
        for p in _SRC.rglob("*.py")
        if "AnthropicLLMService" in p.read_text(encoding="utf-8")
    }
    assert offenders == set()


def test_the_model_default_is_an_alias_not_a_provider_id():
    """A provider model id here would bypass the gateway's alias map entirely and
    be rejected by the proxy — loudly, but only at the first voice session."""
    from src.pipeline.factory import PipelineConfig

    assert PipelineConfig().llm_model == "voice-intake"
    assert "claude" not in PipelineConfig().llm_model


def test_each_voice_workload_reads_its_own_alias_setting():
    """Three pipelines, three settings, so any one can be repointed alone.

    Being able to move a single workload — to a local model, to a cheaper tier —
    IS the deliverable of this migration; a shared knob silently removes it while
    every test still passes. Re-collapsing these into one setting is exactly the
    kind of tidy-up that looks like a simplification, so it is pinned here.
    """
    from src.config import Settings

    settings = Settings()
    aliases = {
        settings.voice_intake_model,
        settings.voice_screening_model,
        settings.voice_feedback_model,
    }
    assert aliases == {"voice-intake", "voice-screening", "voice-feedback"}

    main = (_SRC / "main.py").read_text(encoding="utf-8")
    assert "settings.voice_llm_model" not in main, "a shared model knob is back"
    # Five PipelineConfig sites, each naming one of the three.
    assert main.count("llm_model=settings.voice_intake_model,") == 2
    assert main.count("llm_model=settings.voice_feedback_model,") == 2
    assert main.count("llm_model=settings.voice_screening_model,") == 1


def test_every_voice_alias_exists_in_the_gateway_config():
    """A setting naming an alias litellm does not serve fails only when a
    recruiter connects, as a 400 from the proxy mid-session."""
    config = _REPO_ROOT / "litellm-config.yaml"
    if not config.exists():
        pytest.skip("repo root not reachable from this checkout")

    served = set(re.findall(r"^\s*-\s*model_name:\s*(\S+)", config.read_text(), re.M))
    assert {"voice-intake", "voice-screening", "voice-feedback"} <= served
