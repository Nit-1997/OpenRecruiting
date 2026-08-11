from copy import deepcopy

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


def normalize_messages_for_gateway(messages: list[dict]) -> list[dict]:
    """Restore the message reshaping the Anthropic adapter used to do for us.

    THIS IS NOT COSMETIC — without it every voice pipeline 400s on its first
    turn. Both failures were reproduced live against the gateway.

    This service's whole kickoff design writes an instruction as a TRAILING
    SYSTEM MESSAGE (`main.py` does it at the greeting and the wrap-up timer on
    all five pipelines) and then runs the LLM. That worked because pipecat's
    `AnthropicLLMAdapter` rewrote the list before it went out
    (`adapters/services/anthropic_adapter.py:121-140`):

      * the FIRST system message became the top-level `system` param;
      * every SUBSEQUENT system message was converted to `role: "user"`;
      * consecutive same-role messages were merged;
      * a list containing ONLY a system message became a user message.

    `OpenAILLMAdapter` is a pass-through, so after phase 7 none of that happens.
    LiteLLM hoists all system messages into Anthropic's `system` param, and what
    is left is either:

      * NOTHING, on a fresh session — 400 "at least one message is required"; or
      * a trailing ASSISTANT message, on a resumed session, which Anthropic
        reads as an assistant PREFILL — 400 "This model does not support
        assistant message prefill. The conversation must end with a user
        message." (claude-sonnet-4-5 accepted prefill; claude-sonnet-5, which
        phase 1 deliberately bumped these aliases to, does not.)

    Applied to a DEEP COPY, never in place. The caller's list is the shared
    LLMContext `messages` that TurnPersistFrameProcessor reads to build the
    transcript; rewriting a kickoff instruction to `user` there would persist
    "Say your brief, warm opening greeting" as something the RECRUITER said.
    That is why this lives here and not at the call sites.
    """
    out: list[dict] = []
    for index, message in enumerate(deepcopy(messages)):
        # The leading system message is the persona; LiteLLM lifts it correctly.
        if message.get("role") == "system" and index > 0:
            message["role"] = "user"
        if out and out[-1].get("role") == message.get("role"):
            previous, current = out[-1].get("content"), message.get("content")
            if isinstance(previous, str) and isinstance(current, str):
                out[-1]["content"] = f"{previous}\n\n{current}"
                continue
        out.append(message)

    # A lone system message leaves the wire with no messages at all.
    if len(out) == 1 and out[0].get("role") == "system":
        out[0]["role"] = "user"
    return out


class GatewayLLMService(OpenAILLMService):
    """OpenAILLMService with the Anthropic adapter's message reshaping restored.

    `build_chat_completion_params` is pipecat's own documented override seam
    ("Subclasses can override this to customize parameters for different
    providers", openai/base_llm.py:236-248) and sits on the live path —
    `get_chat_completions` calls it at :218.
    """

    def build_chat_completion_params(self, params_from_context) -> dict:
        params = super().build_chat_completion_params(params_from_context)
        if params.get("messages"):
            params["messages"] = normalize_messages_for_gateway(params["messages"])
        return params


def create_llm(api_key: str, model: str, base_url: str) -> GatewayLLMService:
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

    Returns a GatewayLLMService, not a bare OpenAILLMService — see
    normalize_messages_for_gateway for why that subclass is load-bearing.
    """
    return GatewayLLMService(
        api_key=api_key,
        model=model,
        base_url=base_url,
    )
