from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.anthropic.llm import AnthropicLLMService


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


def create_anthropic_llm(api_key: str, model: str) -> AnthropicLLMService:
    return AnthropicLLMService(
        api_key=api_key,
        model=model,
        params=AnthropicLLMService.InputParams(enable_prompt_caching=True),
    )
