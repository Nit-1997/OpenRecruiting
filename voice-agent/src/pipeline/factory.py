import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMAssistantAggregatorParams,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.utils.context.llm_context_summarization import LLMContextSummarizationConfig
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies
from pipecat.pipeline.pipeline import Pipeline
from pipecat.adapters.schemas.tools_schema import ToolsSchema

from src.pipeline.services import (
    create_deepgram_stt,
    create_deepgram_tts,
    create_anthropic_llm,
)
from src.pipeline.filler import FillerProcessor
from src.pipeline.markdown_stripper import MarkdownStripper, TTSNameNormalizer
from src.pipeline.end_detector import EndOfConversationDetector
from src.pipeline.input_gate import PostEndInputGate
from src.pipeline.tool_schemas import function_schemas, tool_name
from src.pipeline.interrupt_context_cleaner import InterruptContextCleaner
from src.pipeline.metrics_logger import MetricsLogger


@dataclass
class PipelineConfig:
    deepgram_api_key: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    tts_voice: str = "aura-2-helena-en"
    persona_text: str = ""
    flux_eot_threshold: float = 0.7
    flux_eager_eot_threshold: float | None = None
    flux_eot_timeout_ms: int | None = None
    max_context_tokens: int = 8000
    target_context_tokens: int = 6000
    max_unsummarized_messages: int = 20
    min_messages_after_summary: int = 4
    # v2 intake fields — all optional, default None so v1 callsites are unaffected
    seed_messages: Optional[list] = field(default=None)
    tools: Optional[list] = field(default=None)
    intake_session_id: Optional[str] = field(default=None)
    intake_supabase_client: Optional[Any] = field(default=None)
    intake_tool_dispatch: Optional[Any] = field(default=None)  # callable(tool_name, tool_args, turn_idx) -> dict
    intake_on_user_turn: Optional[Any] = field(default=None)   # callable(text, idx) -> coroutine
    intake_initial_turn_idx: int = 0  # seed from existing session turns to avoid idx collisions on handoff
    # Screening path: a callable(messages) that rewrites the system prompt in place
    # before each LLM run. Unlike the intake refresher (which re-reads the DB), the
    # screening refresher recomputes from an in-memory session dict (no DB round-trip),
    # so it runs ON the event loop. None on every other path → no behaviour change.
    prompt_refresh: Optional[Any] = field(default=None)  # callable(messages: list[dict]) -> None
    # Feedback path only: an RTVIProcessor to insert into the pipeline so the
    # RTVIObserver (attached on the task) can stream user/bot transcripts to the
    # client over the data channel. None on every other path → no behaviour change.
    rtvi_processor: Optional[Any] = field(default=None)
    # Screening/feedback end-of-call paths: an append-only transcript recorder
    # (TranscriptAccumulatorProcessor) inserted after the assistant aggregator.
    # Unlike the shared `messages` list, it survives context-summarization
    # compaction. None on every other path → no behaviour change.
    transcript_accumulator: Optional[Any] = field(default=None)


class PipelineFactory:
    @staticmethod
    def create_pipeline(config: PipelineConfig, transport, end_event: asyncio.Event) -> tuple[Pipeline, list[dict]]:
        stt = create_deepgram_stt(
            api_key=config.deepgram_api_key,
            eot_threshold=config.flux_eot_threshold,
            eager_eot_threshold=config.flux_eager_eot_threshold,
            eot_timeout_ms=config.flux_eot_timeout_ms,
        )
        tts = create_deepgram_tts(
            api_key=config.deepgram_api_key,
            voice=config.tts_voice,
        )
        llm = create_anthropic_llm(
            api_key=config.anthropic_api_key,
            model=config.anthropic_model,
        )

        # Seed messages: system prompt + any prior turns from intake_sessions
        messages = [{"role": "system", "content": config.persona_text}]
        if config.seed_messages:
            messages.extend(config.seed_messages)

        # Build context. For v2, attach tools as standard FunctionSchema objects.
        if config.tools:
            standard_tools = function_schemas(config.tools)
            tools_schema = ToolsSchema(standard_tools=standard_tools)
            context = LLMContext(messages, tools=tools_schema)
        else:
            context = LLMContext(messages)

        summarization_config = LLMContextSummarizationConfig(
            max_context_tokens=config.max_context_tokens,
            target_context_tokens=config.target_context_tokens,
            max_unsummarized_messages=config.max_unsummarized_messages,
            min_messages_after_summary=config.min_messages_after_summary,
        )

        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=ExternalUserTurnStrategies(),
            ),
            assistant_params=LLMAssistantAggregatorParams(
                enable_context_summarization=True,
                context_summarization_config=summarization_config,
            ),
        )

        filler = FillerProcessor(delay_secs=2.0, bot_cooldown_secs=3.0, min_speech_secs=0.3, end_event=end_event)
        md_stripper = MarkdownStripper()
        end_detector = EndOfConversationDetector(end_event)
        name_normalizer = TTSNameNormalizer()
        input_gate = PostEndInputGate(end_event)
        interrupt_cleaner = InterruptContextCleaner(messages)
        metrics = MetricsLogger()

        # v2 intake wiring: PromptRefreshProcessor (pre-LLM) + TurnPersistFrameProcessor (post-LLM).
        pre_llm_processors = []   # run before context_aggregator.user()
        post_llm_processors = []  # run after context_aggregator.assistant()
        persist_processor = None  # outer scope so tool dispatch can read current_user_turn_idx
        if config.intake_session_id is not None and config.intake_supabase_client is not None:
            from src.pipeline.turn_persist import TurnPersistFrameProcessor

            # Persist BOTH roles from the shared `messages` context — it MUST sit
            # AFTER the assistant aggregator so that, on LLMFullResponseEndFrame,
            # messages already holds the completed user + assistant turn. (When it
            # sat upstream of the LLM it only ever saw user TranscriptionFrames →
            # assistant turns were silently dropped, breaking the transcript and
            # the voice↔text handoff context.)
            persist_processor = TurnPersistFrameProcessor(
                supabase_client=config.intake_supabase_client,
                session_id=config.intake_session_id,
                messages=messages,
                on_user_turn=config.intake_on_user_turn,
                initial_idx=config.intake_initial_turn_idx,
            )
            post_llm_processors.append(persist_processor)

            # Prompt refresher: rebuilds system message before each LLM run
            from src.pipeline.prompt_refresher import refresh_system_prompt
            from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
            from pipecat.frames.frames import LLMRunFrame, Frame

            _client = config.intake_supabase_client
            _sid = config.intake_session_id
            _msgs = messages

            class _PromptRefreshProcessor(FrameProcessor):
                async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
                    await super().process_frame(frame, direction)
                    if isinstance(frame, LLMRunFrame):
                        # refresh_system_prompt does a BLOCKING Supabase .execute().
                        # Run it off the event loop — a synchronous DB round-trip here
                        # starves the aiortc WebRTC transport (it shares this loop),
                        # which drops the peer connection after the first real turn.
                        # Mirrors TurnPersistFrameProcessor._persist_async (to_thread).
                        await asyncio.to_thread(refresh_system_prompt, _client, _sid, _msgs)
                    await self.push_frame(frame, direction)

            pre_llm_processors.append(_PromptRefreshProcessor())

        elif config.prompt_refresh is not None:
            # Screening path: refresh the system prompt from an in-memory session
            # dict (no DB round-trip), so it's safe to run on the event loop.
            from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
            from pipecat.frames.frames import LLMRunFrame, Frame

            _refresh = config.prompt_refresh
            _msgs = messages

            class _InMemoryPromptRefreshProcessor(FrameProcessor):
                async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
                    await super().process_frame(frame, direction)
                    if isinstance(frame, LLMRunFrame):
                        try:
                            _refresh(_msgs)
                        except Exception:
                            pass  # leave the prior prompt in place on any failure
                    await self.push_frame(frame, direction)

            pre_llm_processors.append(_InMemoryPromptRefreshProcessor())

        if config.transcript_accumulator is not None:
            config.transcript_accumulator.bind_messages(messages)
            post_llm_processors.append(config.transcript_accumulator)

        # Register tool dispatch callbacks for v2.
        # Read current_user_turn_idx from persist_processor at call time so each tool
        # invocation gets the idx of the user turn that triggered it, not a hardcoded 0.
        if config.intake_tool_dispatch is not None and config.tools:
            from pipecat.services.llm_service import FunctionCallParams

            _persist_proc_ref = persist_processor  # captured once; may be None if no session wiring

            # Pipecat's register_function inspects the handler signature: a handler
            # with more than ONE parameter is flagged as the deprecated 6-positional-
            # arg API and invoked accordingly. We can't use the kwarg-default
            # closure-binding trick (params, _tn=..., _proc=...) — it has 3 params,
            # gets flagged as deprecated, and pipecat tries to call it with 6 args.
            # Instead, build each handler from a true 1-arg factory that closes over
            # the variables explicitly.
            def _make_tool_handler(tool_name: str, proc_ref):
                async def _handler(params: FunctionCallParams) -> None:
                    turn_idx = proc_ref.current_user_turn_idx if proc_ref is not None else 0
                    # intake_tool_dispatch does a BLOCKING Supabase .execute() (the
                    # update_answer / mark_status write). Thread it so the WebRTC
                    # event loop keeps servicing the call during the DB round-trip —
                    # otherwise the peer connection drops mid-turn.
                    result = await asyncio.to_thread(
                        config.intake_tool_dispatch, tool_name, dict(params.arguments), turn_idx
                    )
                    await params.result_callback(result)
                return _handler

            for tool in config.tools:
                name = tool_name(tool)
                llm.register_function(name, _make_tool_handler(name, _persist_proc_ref))

        pipeline = Pipeline([
            transport.input(),
            *([config.rtvi_processor] if config.rtvi_processor else []),
            stt,
            input_gate,
            *pre_llm_processors,
            context_aggregator.user(),
            filler,
            llm,
            md_stripper,
            end_detector,
            tts,
            name_normalizer,
            transport.output(),
            interrupt_cleaner,
            context_aggregator.assistant(),
            *post_llm_processors,
            metrics,
        ])
        return pipeline, messages
