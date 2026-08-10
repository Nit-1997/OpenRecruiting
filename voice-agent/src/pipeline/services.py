from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.openai.llm import OpenAILLMService


def create_deepgram_stt(
    api_key: str,
    eot_threshold: float | None = None,
    eager_eot_threshold: float | None = None,
    eot_timeout_ms: int | None = None,
) -> DeepgramFluxSTTService:
    params = DeepgramFluxSTTService.InputParams(min_confidence=0.5)
    if eot_threshold is not None:
        params.eot_threshold = eot_threshold
    if eager_eot_threshold is not None:
        params.eager_eot_threshold = eager_eot_threshold
    if eot_timeout_ms is not None:
        params.eot_timeout_ms = eot_timeout_ms

    return DeepgramFluxSTTService(
        api_key=api_key,
        model="flux-general-en",
        sample_rate=16000,
        flux_encoding="linear16",
        should_interrupt=True,
        params=params,
    )


def create_deepgram_tts(api_key: str, voice: str = "aura-2-helena-en") -> DeepgramTTSService:
    return DeepgramTTSService(
        api_key=api_key,
        voice=voice,
        sample_rate=24000,
        encoding="linear16",
    )


def create_llm(api_key: str, model: str, base_url: str) -> OpenAILLMService:
    """The realtime LLM, through the LiteLLM gateway.

    `api_key` is LITELLM_MASTER_KEY and `model` a gateway alias — this function
    names no provider, which is the whole point of phase 7.

    Two deliberate losses, both from swapping the previous provider service out:

    * `enable_prompt_caching` is gone. It was Anthropic's ephemeral cache_control
      and has no equivalent on this path; the spec accepts the cost.
    * `max_tokens` no longer defaults to 4096 — OpenAILLMService leaves it
      NOT_GIVEN, so the provider's own default applies. Left unset on purpose
      rather than hardcoded: pinning 4096 here would silently re-cap every alias
      this service is ever pointed at, and the gateway is where per-alias limits
      belong.
    """
    return OpenAILLMService(
        api_key=api_key,
        model=model,
        base_url=base_url,
    )
