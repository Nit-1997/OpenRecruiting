"""What the pipeline factory hands its LLM service.

READ THIS BEFORE TRUSTING THIS FILE. Every conftest under voice-agent/tests
stubs pipecat into sys.modules, so OpenAILLMService here is a MagicMock. These
tests prove which kwargs THIS REPO passes and which modules it imports. They
prove NOTHING about whether pipecat accepts them, whether the gateway answers,
or whether a tool call survives the round trip — that is what
scripts/smoke_llm_service.py does, inside the built image against a live gateway.

The properties pinned here are the ones a wrong swap breaks silently.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

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


def test_the_service_is_built_against_a_gateway_base_url():
    from pipecat.services.openai.llm import OpenAILLMService

    create_llm(api_key="master-key", model="voice-intake", base_url="http://litellm:4000/v1")

    kwargs = OpenAILLMService.call_args.kwargs
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
