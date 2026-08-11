import asyncio
import hmac
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from src.logging_config import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)
from fastapi.middleware.cors import CORSMiddleware

from aiortc import RTCIceServer
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCRequestHandler,
    SmallWebRTCRequest,
    SmallWebRTCPatchRequest,
    IceCandidate,
)
from pipecat.transports.base_transport import TransportParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frameworks.rtvi import RTVIObserver, RTVIProcessor
from pipecat.frames.frames import EndFrame, ErrorFrame, LLMRunFrame, TTSSpeakFrame

from src.config import get_settings
from src.pipeline.factory import PipelineFactory, PipelineConfig
from src.persona.generator import generate_persona, RoleContext, ScorecardItem
from src.pipeline.markdown_stripper import normalize_phonetic_name
from src.persona.dynamic_intake import build_voice_intake_prompt
from src.pipeline.transcript_accumulator import TranscriptAccumulatorProcessor
from src.pipeline.turn_persist import TurnPersistFrameProcessor
from src.pipeline.tool_dispatch import dispatch_tool_call
from src.session_loader import load_intake_session_for_voice, format_turns_for_llm
from src.persona.screening import build_voice_screening_prompt
from intake_core.tools import INTAKE_TOOLS
from intake_core.coverage_tracker import run_coverage_tracker
from intake_core.screening import (
    ALL_SCREENING_TOOLS,
    handle_mark_question_covered,
    snapshot_questions,
)

SESSION_TIMEOUT_SECS = 600
WRAPUP_WARNING_SECS = 570

INTAKE_SESSION_TIMEOUT_SECS = 900
INTAKE_WRAPUP_WARNING_SECS = 870

ERROR_MESSAGES = {
    "default": "I'm sorry, I encountered a brief issue. Could you please repeat that?",
    "fatal": "I'm sorry, something went wrong and I need to restart. Please reconnect in a moment.",
}

_http_client: httpx.AsyncClient | None = None
_webrtc_handler: SmallWebRTCRequestHandler | None = None

from src.intake.drain import DEFAULT_SAFETY_TIMEOUT_S, drain_session as _drain_session
from src.intake.session_registry import SessionRegistry, SessionNotFound

intake_session_registry = SessionRegistry()

INTERNAL_API_SECRET = os.environ.get("INTERNAL_API_SECRET", "")


def _verify_internal_secret(request: Request) -> None:
    provided = request.headers.get("X-Internal-Secret", "")
    if not INTERNAL_API_SECRET or not hmac.compare_digest(provided, INTERNAL_API_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")


def _build_ice_servers() -> list[RTCIceServer]:
    settings = get_settings()
    servers = [RTCIceServer(urls=url) for url in settings.ice_stun_servers]
    if settings.turn_server_url:
        servers.append(RTCIceServer(
            urls=settings.turn_server_url,
            username=settings.turn_username,
            credential=settings.turn_credential,
        ))
    return servers


def _get_headers() -> dict:
    settings = get_settings()
    return {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "Content-Type": "application/json",
    }


def _rest_url(path: str) -> str:
    settings = get_settings()
    return f"{settings.supabase_url}/rest/v1/{path}"


async def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        )
    return _http_client


async def validate_session_token(session_token: str) -> dict | None:
    client = await _get_http_client()
    resp = await client.get(
        _rest_url("recall_bots"),
        headers=_get_headers(),
        params={
            "select": "id,recall_bot_id,voice_session_token,voice_session_status,candidate_round_id",
            "voice_session_token": f"eq.{session_token}",
        },
    )
    if resp.status_code != 200:
        logger.error(f"Supabase query failed: {resp.status_code} {resp.text}")
        return None
    data = resp.json()
    if not data:
        return None
    record = data[0]
    if record.get("voice_session_status") in ("completed", "error"):
        logger.info(f"Session already {record['voice_session_status']}, rejecting reconnection")
        return None
    return record


async def fetch_role_and_scorecard(candidate_round_id: str) -> tuple[RoleContext | None, list[ScorecardItem]]:
    client = await _get_http_client()
    headers = _get_headers()

    resp = await client.get(
        _rest_url("candidate_rounds"),
        headers=headers,
        params={
            "select": "round_id,rounds!inner(requisition_id,feedback_questions(question_number,heading,description),requisitions!inner(role_title,experience_min_years,experience_max_years,must_have_skills,good_to_have_skills,job_description,intake_notes))",
            "id": f"eq.{candidate_round_id}",
            "rounds.feedback_questions.deleted_at": "is.null",
            "rounds.feedback_questions.order": "question_number",
        },
    )
    if resp.status_code != 200 or not resp.json():
        logger.error(f"Failed to fetch role context for {candidate_round_id}: status={resp.status_code}, body={resp.text[:200]}")
        return None, []

    cr_data = resp.json()[0]
    rounds = cr_data.get("rounds", {})
    req = rounds.get("requisitions", {})
    exp_min = req.get("experience_min_years", 0)
    exp_max = req.get("experience_max_years")
    experience_range = f"{exp_min}-{exp_max} years" if exp_max else f"{exp_min}+ years"
    role_context = RoleContext(
        role_title=req.get("role_title", ""),
        experience_range=experience_range,
        must_have_skills=req.get("must_have_skills", []) or [],
        good_to_have_skills=req.get("good_to_have_skills", []) or [],
        job_description=req.get("job_description", ""),
        intake_notes=req.get("intake_notes", ""),
    )

    scorecard = [
        ScorecardItem(
            question_number=q["question_number"],
            heading=q["heading"],
            description=q.get("description", ""),
        )
        for q in rounds.get("feedback_questions", [])
    ]

    return role_context, scorecard


def format_conversation_transcript(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content or role == "system":
            continue
        content = content.replace("[END]", "")
        content = content.replace("[interrupted — user only heard partial response]", "")
        content = normalize_phonetic_name(content)
        content = content.strip()
        if not content:
            continue
        speaker = "Scout" if role == "assistant" else "Interviewer"
        lines.append(f"{speaker}: {content}")
    return "\n\n".join(lines)


async def store_feedback_transcript(candidate_round_id: str, transcript_text: str):
    if not transcript_text.strip():
        logger.warning(f"Empty voice transcript for {candidate_round_id}, skipping store")
        return
    client = await _get_http_client()
    headers = {**_get_headers(), "Prefer": "return=minimal"}
    resp = await client.get(
        _rest_url("transcripts"),
        headers=_get_headers(),
        params={
            "select": "id",
            "candidate_round_id": f"eq.{candidate_round_id}",
        },
    )
    if resp.status_code == 200 and resp.json():
        await client.patch(
            _rest_url("transcripts"),
            headers=headers,
            params={"candidate_round_id": f"eq.{candidate_round_id}"},
            json={
                "feedback_transcript": transcript_text,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info(f"Updated feedback_transcript for {candidate_round_id} ({len(transcript_text)} chars)")
    else:
        await client.post(
            _rest_url("transcripts"),
            headers=headers,
            json={
                "candidate_round_id": candidate_round_id,
                "feedback_transcript": transcript_text,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info(f"Inserted feedback_transcript for {candidate_round_id} ({len(transcript_text)} chars)")


async def update_voice_status(recall_bot_id: str, voice_status: str, feedback_status: str | None = None):
    client = await _get_http_client()
    update_data = {"voice_session_status": voice_status}
    if feedback_status:
        update_data["feedback_status"] = feedback_status
    headers = {**_get_headers(), "Prefer": "return=minimal"}
    resp = await client.patch(
        _rest_url("recall_bots"),
        headers=headers,
        params={"id": f"eq.{recall_bot_id}"},
        json=update_data,
    )
    if resp.status_code not in (200, 204):
        logger.error(f"Failed to update voice status: {resp.status_code} {resp.text}")


async def leave_recall_meeting(recall_bot_id: str):
    settings = get_settings()
    if not settings.recall_api_key or not recall_bot_id:
        logger.warning(f"Cannot leave meeting: missing recall_api_key or recall_bot_id")
        return
    client = await _get_http_client()
    url = f"{settings.recall_base_url}/bot/{recall_bot_id}/leave_call"
    headers = {"Authorization": f"Token {settings.recall_api_key}"}
    for attempt in range(3):
        try:
            resp = await client.post(url, headers=headers)
            if resp.status_code in (200, 204):
                logger.info(f"Bot {recall_bot_id} left the meeting")
                return
            logger.warning(f"leave_call attempt {attempt+1} failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.warning(f"leave_call attempt {attempt+1} error: {e}")
        if attempt < 2:
            await asyncio.sleep(2 ** attempt)
    logger.error(f"All leave_call attempts failed for bot {recall_bot_id}")


async def validate_intake_session_token(session_token: str) -> dict | None:
    client = await _get_http_client()
    resp = await client.get(
        _rest_url("requisitions"),
        headers=_get_headers(),
        params={
            "select": "id,role_title,experience_min_years,experience_max_years,must_have_skills,good_to_have_skills,job_description,intake_notes,intake_voice_session_token,intake_voice_session_status",
            "intake_voice_session_token": f"eq.{session_token}",
        },
    )
    if resp.status_code != 200:
        logger.error(f"Supabase intake query failed: {resp.status_code} {resp.text}")
        return None
    data = resp.json()
    if not data:
        logger.warning(f"Intake session token not found in DB: {session_token[:8]}...")
        return None
    record = data[0]
    if record.get("intake_voice_session_status") in ("completed", "error"):
        logger.info(f"Intake session already {record['intake_voice_session_status']}, rejecting")
        return None
    logger.info(f"Intake session validated for requisition {record['id']}")
    return record


async def store_intake_transcript(requisition_id: str, transcript_text: str):
    if not transcript_text.strip():
        logger.warning(f"Empty intake transcript for {requisition_id}, skipping store")
        return
    client = await _get_http_client()
    headers = {**_get_headers(), "Prefer": "return=minimal"}

    for attempt in range(2):
        resp = await client.patch(
            _rest_url("requisitions"),
            headers=headers,
            params={"id": f"eq.{requisition_id}"},
            json={"intake_transcript": transcript_text},
        )
        if resp.status_code in (200, 204):
            logger.info(f"Stored intake_transcript for requisition {requisition_id} ({len(transcript_text)} chars)")
            return
        logger.error(f"Failed to store intake transcript (attempt {attempt+1}): {resp.status_code} {resp.text}")
        if attempt == 0:
            await asyncio.sleep(2)

    raise RuntimeError(f"Failed to store intake transcript for {requisition_id} after 2 attempts")


async def update_intake_voice_status(requisition_id: str, voice_status: str):
    client = await _get_http_client()
    headers = {**_get_headers(), "Prefer": "return=minimal"}

    for attempt in range(2):
        resp = await client.patch(
            _rest_url("requisitions"),
            headers=headers,
            params={"id": f"eq.{requisition_id}"},
            json={"intake_voice_session_status": voice_status},
        )
        if resp.status_code in (200, 204):
            return
        logger.error(f"Failed to update intake voice status (attempt {attempt+1}): {resp.status_code} {resp.text}")
        if attempt == 0:
            await asyncio.sleep(2)

    raise RuntimeError(f"Failed to update intake voice status to '{voice_status}' after 2 attempts")


def _rpc_url(function_name: str) -> str:
    settings = get_settings()
    return f"{settings.supabase_url}/rest/v1/rpc/{function_name}"


async def charge_intake_credit(requisition_id: str):
    client = await _get_http_client()
    headers = _get_headers()

    req_resp = await client.get(
        _rest_url("requisitions"),
        headers=headers,
        params={
            "select": "organization_id,intake_credit_charged",
            "id": f"eq.{requisition_id}",
        },
    )
    if req_resp.status_code != 200 or not req_resp.json():
        logger.warning(f"Intake credit: Could not resolve org for req={requisition_id}")
        return

    req = req_resp.json()[0]
    if req.get("intake_credit_charged"):
        logger.info(f"Intake credit: Already charged for req={requisition_id}")
        return

    org_id = req.get("organization_id")
    if not org_id:
        logger.warning(f"Intake credit: No org_id on req={requisition_id}")
        return

    rpc_resp = await client.post(
        _rpc_url("use_credit_atomic"),
        headers={**headers, "Content-Type": "application/json"},
        json={"p_org_id": org_id, "p_credit_type": "intake"},
    )
    if rpc_resp.status_code == 200:
        source = rpc_resp.json()
        if source == "exhausted":
            logger.warning(f"Intake credit: Exhausted for org={org_id} req={requisition_id}")
            return
        logger.info(f"Intake credit: Charged ({source}) for org={org_id} req={requisition_id}")
    else:
        logger.error(f"Intake credit: RPC failed: {rpc_resp.status_code} {rpc_resp.text}")
        return

    mark_headers = {**_get_headers(), "Prefer": "return=minimal"}
    await client.patch(
        _rest_url("requisitions"),
        headers=mark_headers,
        params={"id": f"eq.{requisition_id}"},
        json={"intake_credit_charged": True},
    )


def format_intake_transcript(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content or role == "system":
            continue
        content = content.replace("[END]", "")
        content = content.replace("[interrupted — user only heard partial response]", "")
        content = normalize_phonetic_name(content)
        content = content.strip()
        if not content:
            continue
        speaker = "Scout" if role == "assistant" else "Recruiter"
        lines.append(f"{speaker}: {content}")
    return "\n\n".join(lines)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _webrtc_handler
    settings = get_settings()
    ice_servers = _build_ice_servers()
    _webrtc_handler = SmallWebRTCRequestHandler(ice_servers=ice_servers)
    logger.info("Scout Voice Agent starting")
    logger.info(
        "LLM aliases: intake=%s screening=%s feedback=%s",
        settings.voice_intake_model,
        settings.voice_screening_model,
        settings.voice_feedback_model,
    )
    logger.info(f"ICE servers: {[s.urls for s in ice_servers]}")
    yield
    if _webrtc_handler:
        await _webrtc_handler.close()
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
    logger.info("Scout Voice Agent shutting down")


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionLogger:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            client = scope.get("client", ("unknown", 0))
            path = scope.get("path", "unknown")
            headers = dict(scope.get("headers", []))
            origin = headers.get(b"origin", b"none").decode()
            logger.info(
                f"ASGI {scope['type']} connection: path={path} "
                f"client={client[0]}:{client[1]} origin={origin}"
            )
        await self.app(scope, receive, send)

app.add_middleware(ConnectionLogger)


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _run_feedback_pipeline(connection, recall_bot: dict):
    setup_start = asyncio.get_event_loop().time()
    supabase_bot_id = recall_bot["id"]
    recall_bot_id = recall_bot.get("recall_bot_id")
    candidate_round_id = recall_bot.get("candidate_round_id")

    role_context, scorecard = await fetch_role_and_scorecard(candidate_round_id)

    if role_context and scorecard:
        persona_text = generate_persona(role_context, scorecard)
    else:
        persona_text = (
            "You are mayzul, a friendly recruiter coordinator collecting interview feedback. "
            "Ask the interviewer how the interview went, what stood out, and their overall recommendation. "
            "Keep responses concise -- 1-2 sentences. "
            "When you have enough feedback, thank the interviewer and say goodbye. End your final message with [END]."
        )

    settings = get_settings()
    config = PipelineConfig(
        deepgram_api_key=settings.voice_deepgram_api_key,
        llm_api_key=settings.litellm_master_key,
        llm_model=settings.voice_feedback_model,
        llm_base_url=settings.llm_gateway_url + "/v1",
        tts_voice=settings.voice_tts_voice,
        persona_text=persona_text,
        max_context_tokens=settings.max_context_tokens,
        target_context_tokens=settings.target_context_tokens,
        max_unsummarized_messages=settings.max_unsummarized_messages,
        min_messages_after_summary=settings.min_messages_after_summary,
        flux_eot_threshold=settings.flux_eot_threshold,
        flux_eager_eot_threshold=settings.flux_eager_eot_threshold,
        flux_eot_timeout_ms=settings.flux_eot_timeout_ms,
    )

    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    end_event = asyncio.Event()
    session_ended = asyncio.Event()
    pipeline, messages = PipelineFactory.create_pipeline(config, transport, end_event)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            allow_interruptions=True,
        ),
    )

    async def _end_session(reason: str):
        if session_ended.is_set():
            return
        session_ended.set()
        session_duration_ms = int((asyncio.get_event_loop().time() - setup_start) * 1000)
        logger.info("voice_session_end", extra={
            "event": "voice_session_end",
            "bot_id": supabase_bot_id,
            "reason": reason,
            "session_duration_ms": session_duration_ms,
            "feedback_status": "completed" if reason == "conversation_complete" else "partial",
        })
        try:
            transcript_text = format_conversation_transcript(messages)
            await store_feedback_transcript(candidate_round_id, transcript_text)
        except Exception as e:
            logger.error(f"Failed to store voice transcript: {e}")
        fb_status = "completed" if reason == "conversation_complete" else "partial"
        await update_voice_status(supabase_bot_id, "completed", feedback_status=fb_status)
        await leave_recall_meeting(recall_bot_id)

    async def _watch_end_event():
        await end_event.wait()
        logger.info("End marker detected, queueing EndFrame for graceful audio flush")
        await task.queue_frames([EndFrame()])
        await asyncio.sleep(8)
        if not session_ended.is_set():
            logger.warning("EndFrame safety timeout (8s) — force cancelling pipeline")
            await _end_session("conversation_complete")
            await task.cancel()

    async def _session_timer():
        await asyncio.sleep(WRAPUP_WARNING_SECS)
        if session_ended.is_set():
            return
        logger.info(f"Session approaching time limit, injecting wrap-up")
        messages.append(
            {"role": "system", "content": "You are running low on time. Wrap up NOW. If you haven't asked for the overall assessment yet, ask it immediately in one sentence. If you already have it, thank the interviewer and say goodbye. End your message with [END]."}
        )
        await task.queue_frames([LLMRunFrame()])
        await asyncio.sleep(SESSION_TIMEOUT_SECS - WRAPUP_WARNING_SECS)
        if session_ended.is_set():
            return
        logger.info(f"Hard time limit reached")
        try:
            await task.queue_frames([
                TTSSpeakFrame(text="Thanks so much for your time. I have everything I need. Have a great day!", append_to_context=False)
            ])
            await asyncio.sleep(4)
        except Exception:
            pass
        await _end_session("time_limit")
        await task.cancel()

    bg_tasks: list[asyncio.Task] = []
    greeting_sent = False

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        nonlocal greeting_sent
        if greeting_sent:
            logger.warning("on_client_connected fired again, skipping duplicate greeting")
            return
        greeting_sent = True
        pipeline_ready_time = asyncio.get_event_loop().time()
        setup_ms = int((pipeline_ready_time - setup_start) * 1000)
        logger.info("voice_session_start", extra={
            "event": "voice_session_start",
            "bot_id": supabase_bot_id,
            "candidate_round_id": candidate_round_id,
            "session_type": "feedback",
            "setup_ms": setup_ms,
        })
        await update_voice_status(supabase_bot_id, "active")
        messages.append(
            {"role": "system", "content": "Say a brief hello, state that you're collecting interview feedback for the role, and immediately ask about the first scorecard topic. Keep it to 2 sentences."}
        )
        await task.queue_frames([LLMRunFrame()])
        bg_tasks.append(asyncio.create_task(_watch_end_event()))
        bg_tasks.append(asyncio.create_task(_session_timer()))

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Voice client disconnected for bot {supabase_bot_id}")
        await _end_session("client_disconnected")
        await task.cancel()

    @task.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(task, participant):
        logger.info(f"Participant joined voice session: {participant}")

    @task.event_handler("on_participant_left")
    async def on_participant_left(task, participant, reason):
        logger.info(f"Participant left voice session: {participant}, reason: {reason}")
        await _end_session("participant_left")
        await task.cancel()

    @task.event_handler("on_pipeline_error")
    async def on_pipeline_error(task, frame: ErrorFrame):
        logger.error("voice_pipeline_error", extra={
            "event": "voice_pipeline_error",
            "bot_id": supabase_bot_id,
            "error": str(frame.error),
            "fatal": frame.fatal,
        }, exc_info=frame.exception)
        if frame.fatal:
            msg = ERROR_MESSAGES["fatal"]
            await update_voice_status(supabase_bot_id, "error")
        else:
            msg = ERROR_MESSAGES["default"]
        try:
            await task.queue_frames([
                TTSSpeakFrame(text=msg, append_to_context=False)
            ])
        except Exception as e:
            logger.error(f"Failed to speak error message: {e}")

    runner = PipelineRunner(handle_sigint=False)
    logger.info(f"Voice pipeline starting for bot {supabase_bot_id}")
    try:
        await runner.run(task)
    except Exception as e:
        logger.error(f"Voice pipeline error for bot {supabase_bot_id}: {e}")
        await update_voice_status(supabase_bot_id, "error")
    finally:
        for t in bg_tasks:
            t.cancel()
        if end_event.is_set() and not session_ended.is_set():
            logger.info("Pipeline flushed after EndFrame, waiting 1.5s for Recall audio relay")
            await asyncio.sleep(1.5)
            await _end_session("conversation_complete")
        elif not session_ended.is_set():
            await _end_session("unknown")
        logger.info(f"Voice pipeline completed for bot {supabase_bot_id}")


@app.post("/api/offer/{session_token}")
async def voice_offer(session_token: str, request: Request, background_tasks: BackgroundTasks):
    recall_bot = await validate_session_token(session_token)
    if not recall_bot:
        raise HTTPException(status_code=403, detail="Invalid or expired session token")

    stored_token = str(recall_bot.get("voice_session_token", ""))
    if not secrets.compare_digest(session_token, stored_token):
        raise HTTPException(status_code=403, detail="Token mismatch")

    body = await request.json()
    sdp_request = SmallWebRTCRequest(
        sdp=body["sdp"],
        type=body["type"],
        pc_id=body.get("pc_id"),
        restart_pc=body.get("restart_pc"),
        request_data=body.get("request_data"),
    )

    async def on_connection(connection):
        background_tasks.add_task(_run_feedback_pipeline, connection, recall_bot)

    answer = await _webrtc_handler.handle_web_request(sdp_request, on_connection)
    return answer


async def _run_intake_pipeline(connection, requisition: dict):
    setup_start = asyncio.get_event_loop().time()
    requisition_id = requisition["id"]

    exp_min = requisition.get("experience_min_years", 0)
    exp_max = requisition.get("experience_max_years")
    experience_range = f"{exp_min}-{exp_max} years" if exp_max else f"{exp_min}+ years" if exp_min else ""

    intake_context = IntakeContext(
        role_title=requisition.get("role_title", ""),
        experience_range=experience_range,
        must_have_skills=requisition.get("must_have_skills") or [],
        good_to_have_skills=requisition.get("good_to_have_skills") or [],
        job_description=requisition.get("job_description", "") or "",
        intake_notes=requisition.get("intake_notes", "") or "",
    )
    persona_text = generate_intake_persona(intake_context)

    settings = get_settings()
    config = PipelineConfig(
        deepgram_api_key=settings.voice_deepgram_api_key,
        llm_api_key=settings.litellm_master_key,
        llm_model=settings.voice_intake_model,
        llm_base_url=settings.llm_gateway_url + "/v1",
        tts_voice=settings.voice_tts_voice,
        persona_text=persona_text,
        max_context_tokens=settings.max_context_tokens,
        target_context_tokens=settings.target_context_tokens,
        max_unsummarized_messages=settings.max_unsummarized_messages,
        min_messages_after_summary=settings.min_messages_after_summary,
        flux_eot_threshold=settings.flux_eot_threshold,
        flux_eager_eot_threshold=settings.flux_eager_eot_threshold,
        flux_eot_timeout_ms=settings.flux_eot_timeout_ms,
    )

    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    end_event = asyncio.Event()
    session_ended = asyncio.Event()
    pipeline, messages = PipelineFactory.create_pipeline(config, transport, end_event)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            allow_interruptions=True,
        ),
    )

    session_start_time: float | None = None

    async def _end_intake_session(reason: str):
        if session_ended.is_set():
            return
        session_ended.set()
        session_duration_ms = int((asyncio.get_event_loop().time() - setup_start) * 1000)
        logger.info("voice_session_end", extra={
            "event": "voice_session_end",
            "requisition_id": requisition_id,
            "reason": reason,
            "session_type": "intake",
            "session_duration_ms": session_duration_ms,
        })
        transcript_text = ""
        try:
            transcript_text = format_intake_transcript(messages)
            await store_intake_transcript(requisition_id, transcript_text)
        except Exception as e:
            logger.error(f"Failed to store intake transcript: {e}")
        elapsed = (asyncio.get_event_loop().time() - session_start_time) if session_start_time else 0
        if reason == "client_disconnected" and elapsed < 5 and not transcript_text.strip():
            logger.info(f"Instant disconnect ({elapsed:.1f}s, empty transcript) — resetting to pending for retry")
            await update_intake_voice_status(requisition_id, "pending")
        else:
            await update_intake_voice_status(requisition_id, "completed")
            try:
                await charge_intake_credit(requisition_id)
            except Exception as e:
                logger.error(f"Failed to charge intake credit for {requisition_id}: {e}")

    async def _watch_end_event():
        await end_event.wait()
        logger.info("Intake end marker detected, queueing EndFrame")
        await task.queue_frames([EndFrame()])
        await asyncio.sleep(8)
        if not session_ended.is_set():
            logger.warning("Intake EndFrame safety timeout (8s) — force cancelling")
            await _end_intake_session("conversation_complete")
            await task.cancel()

    async def _intake_session_timer():
        await asyncio.sleep(INTAKE_WRAPUP_WARNING_SECS)
        if session_ended.is_set():
            return
        logger.info("Intake session approaching time limit, injecting wrap-up")
        messages.append(
            {"role": "system", "content": "You are running low on time. Wrap up NOW. If you haven't covered all topics yet, skip to the closing. Thank the recruiter and say goodbye. End your message with [END]."}
        )
        await task.queue_frames([LLMRunFrame()])
        await asyncio.sleep(INTAKE_SESSION_TIMEOUT_SECS - INTAKE_WRAPUP_WARNING_SECS)
        if session_ended.is_set():
            return
        logger.info("Intake hard time limit reached")
        try:
            await task.queue_frames([
                TTSSpeakFrame(text="Thanks so much for your time. I have everything I need to put together a great interview plan. Have a wonderful day!", append_to_context=False)
            ])
            await asyncio.sleep(4)
        except Exception:
            pass
        await _end_intake_session("time_limit")
        await task.cancel()

    bg_tasks: list[asyncio.Task] = []
    greeting_sent = False

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        nonlocal session_start_time, greeting_sent
        if greeting_sent:
            logger.warning("Intake on_client_connected fired again, skipping duplicate greeting")
            return
        greeting_sent = True
        session_start_time = asyncio.get_event_loop().time()
        setup_ms = int((session_start_time - setup_start) * 1000)
        logger.info("voice_session_start", extra={
            "event": "voice_session_start",
            "requisition_id": requisition_id,
            "session_type": "intake",
            "setup_ms": setup_ms,
        })
        await update_intake_voice_status(requisition_id, "active")
        messages.append(
            {"role": "system", "content": "Say a brief hello, introduce yourself, state you're here to learn about the role and build an interview plan, and immediately ask about the first intake topic. Keep it to 2 sentences."}
        )
        await task.queue_frames([LLMRunFrame()])
        bg_tasks.append(asyncio.create_task(_watch_end_event()))
        bg_tasks.append(asyncio.create_task(_intake_session_timer()))

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Intake voice client disconnected for requisition {requisition_id}")
        await _end_intake_session("client_disconnected")
        await task.cancel()

    @task.event_handler("on_pipeline_error")
    async def on_pipeline_error(task, frame: ErrorFrame):
        logger.error("voice_pipeline_error", extra={
            "event": "voice_pipeline_error",
            "requisition_id": requisition_id,
            "error": str(frame.error),
            "fatal": frame.fatal,
        }, exc_info=frame.exception)
        if frame.fatal:
            msg = ERROR_MESSAGES["fatal"]
            await update_intake_voice_status(requisition_id, "error")
        else:
            msg = ERROR_MESSAGES["default"]
        try:
            await task.queue_frames([
                TTSSpeakFrame(text=msg, append_to_context=False)
            ])
        except Exception as e:
            logger.error(f"Failed to speak error message: {e}")

    runner = PipelineRunner(handle_sigint=False)
    logger.info(f"Intake voice pipeline starting for requisition {requisition_id}")
    try:
        await runner.run(task)
    except Exception as e:
        logger.error(f"Intake voice pipeline error for requisition {requisition_id}: {e}")
        await update_intake_voice_status(requisition_id, "error")
    finally:
        for t in bg_tasks:
            t.cancel()
        if end_event.is_set() and not session_ended.is_set():
            logger.info("Intake pipeline flushed after EndFrame, waiting 1.5s")
            await asyncio.sleep(1.5)
            await _end_intake_session("conversation_complete")
        elif not session_ended.is_set():
            await _end_intake_session("unknown")
        logger.info(f"Intake voice pipeline completed for requisition {requisition_id}")


@app.post("/api/offer/intake/{session_token}")
async def intake_offer(session_token: str, request: Request, background_tasks: BackgroundTasks):
    requisition = await validate_intake_session_token(session_token)
    if not requisition:
        raise HTTPException(status_code=403, detail="Invalid or expired intake session token")

    stored_token = str(requisition.get("intake_voice_session_token", ""))
    if not secrets.compare_digest(session_token, stored_token):
        raise HTTPException(status_code=403, detail="Token mismatch")

    body = await request.json()
    sdp_request = SmallWebRTCRequest(
        sdp=body["sdp"],
        type=body["type"],
        pc_id=body.get("pc_id"),
        restart_pc=body.get("restart_pc"),
        request_data=body.get("request_data"),
    )

    async def on_connection(connection):
        background_tasks.add_task(_run_intake_pipeline, connection, requisition)

    answer = await _webrtc_handler.handle_web_request(sdp_request, on_connection)
    return answer


@app.patch("/api/offer/{session_token}")
async def ice_candidate_feedback(session_token: str, request: Request):
    body = await request.json()
    patch_request = SmallWebRTCPatchRequest(
        pc_id=body["pc_id"],
        candidates=[IceCandidate(**c) for c in body.get("candidates", [])],
    )
    await _webrtc_handler.handle_patch_request(patch_request)
    return {"status": "ok"}


@app.patch("/api/offer/intake/{session_token}")
async def ice_candidate_intake(session_token: str, request: Request):
    body = await request.json()
    patch_request = SmallWebRTCPatchRequest(
        pc_id=body["pc_id"],
        candidates=[IceCandidate(**c) for c in body.get("candidates", [])],
    )
    await _webrtc_handler.handle_patch_request(patch_request)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Fallback feedback voice session
# ---------------------------------------------------------------------------
# In-app voice feedback for the case where the interview was off-platform OR
# the bot did not capture a usable transcript. Mirrors the intake voice flow
# but pinned to candidate_rounds.feedback_voice_session_token.
# ---------------------------------------------------------------------------

FALLBACK_FEEDBACK_SESSION_TIMEOUT_SECS = 900
FALLBACK_FEEDBACK_WRAPUP_WARNING_SECS = 870


# Max time a pending voice token can sit before we treat it as stale.
# After this, /api/offer/feedback/{token} returns 403 even if the token
# matches and status is "pending".
FALLBACK_FEEDBACK_TOKEN_TTL_SECS = 3600


async def validate_fallback_feedback_session_token(session_token: str) -> dict | None:
    client = await _get_http_client()
    resp = await client.get(
        _rest_url("candidate_rounds"),
        headers=_get_headers(),
        params={
            "select": (
                "id,feedback_voice_session_token,feedback_voice_session_status,"
                "feedback_voice_session_started_at"
            ),
            "feedback_voice_session_token": f"eq.{session_token}",
        },
    )
    if resp.status_code != 200:
        logger.error(f"Supabase fallback feedback query failed: {resp.status_code} {resp.text}")
        return None
    data = resp.json()
    if not data:
        logger.warning(f"Fallback feedback session token not found in DB: {session_token[:8]}...")
        return None
    record = data[0]
    status = record.get("feedback_voice_session_status")
    # Accept BOTH the first offer (pending) and re-offers of an already-claimed
    # session (active). The pipecat SmallWebRTCTransport renegotiates / reconnects
    # mid-call (a fresh SDP offer, sometimes with a new pc_id); 403-ing those
    # re-offers tears the call down and spins a connect->drop->reconnect loop, so
    # inbound audio never stabilizes (interviewer_chars stays 0). This mirrors the
    # intake offer path, which proceeds whenever active_modality is already
    # "voice". Only terminal states (completed/error) are non-claimable. The token
    # itself — minted fresh per /start-voice — is the real two-tab guard.
    if status not in ("pending", "active"):
        logger.info(
            f"Fallback feedback session for candidate_round {record['id']} not claimable "
            f"(status={status}); rejecting offer."
        )
        return None
    started_at_str = record.get("feedback_voice_session_started_at")
    if started_at_str:
        try:
            started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - started_at).total_seconds()
            if age > FALLBACK_FEEDBACK_TOKEN_TTL_SECS:
                logger.warning(
                    f"Fallback feedback token for candidate_round {record['id']} expired "
                    f"({age:.0f}s > {FALLBACK_FEEDBACK_TOKEN_TTL_SECS}s); rejecting."
                )
                return None
        except ValueError:
            pass
    logger.info(f"Fallback feedback session validated for candidate_round {record['id']}")
    return record


async def claim_fallback_feedback_session(
    candidate_round_id: str, session_token: str
) -> bool:
    """Ensure this session is 'active' for this exact token (idempotent).

    Transitions pending -> active on the FIRST offer, and is a no-op success on
    RE-offers that are already 'active' (the pipecat client renegotiates /
    reconnects mid-call — see validate_fallback_feedback_session_token). Returns
    False only when the row is terminal (completed/error) or the token no longer
    matches — i.e. a genuinely superseded/different session. The PATCH is
    constrained by id + token + status IN (pending, active); the token (minted
    fresh per /start-voice) is the two-tab guard, so accepting 'active' re-offers
    here does NOT let a second tab hijack a different session.
    """
    client = await _get_http_client()
    headers = {**_get_headers(), "Prefer": "return=representation"}
    resp = await client.patch(
        _rest_url("candidate_rounds"),
        headers=headers,
        params={
            "id": f"eq.{candidate_round_id}",
            "feedback_voice_session_token": f"eq.{session_token}",
            "feedback_voice_session_status": "in.(pending,active)",
        },
        json={"feedback_voice_session_status": "active"},
    )
    if resp.status_code not in (200, 204):
        logger.error(
            f"Claim of fallback feedback session failed: {resp.status_code} {resp.text}"
        )
        return False
    rows = resp.json() if resp.text else []
    if not rows:
        logger.info(
            f"Claim lost for candidate_round {candidate_round_id} "
            f"(another offer already active or row not pending)"
        )
        return False
    return True


async def update_fallback_feedback_voice_status(
    candidate_round_id: str, voice_session_token: str, voice_status: str
):
    """Token-scoped status update.

    Constrained by (id, voice_session_token, status IN ('pending','active'))
    so an old pipeline task cannot overwrite the status of a row that has
    since been claimed by a fresher session. A no-op result is expected and
    safe — the row already moved on.
    """
    client = await _get_http_client()
    headers = {**_get_headers(), "Prefer": "return=representation"}
    for attempt in range(2):
        resp = await client.patch(
            _rest_url("candidate_rounds"),
            headers=headers,
            params={
                "id": f"eq.{candidate_round_id}",
                "feedback_voice_session_token": f"eq.{voice_session_token}",
                "feedback_voice_session_status": "in.(pending,active)",
            },
            json={"feedback_voice_session_status": voice_status},
        )
        if resp.status_code in (200, 204):
            rows = resp.json() if resp.text else []
            if not rows:
                logger.info(
                    f"Status update to '{voice_status}' skipped — row no longer "
                    f"matches token for candidate_round {candidate_round_id} "
                    f"(superseded by another session)"
                )
            return
        logger.error(
            f"Failed to update fallback feedback voice status "
            f"(attempt {attempt+1}): {resp.status_code} {resp.text}"
        )
        if attempt == 0:
            await asyncio.sleep(2)
    logger.error(
        f"All attempts failed to update fallback feedback voice status "
        f"to '{voice_status}' for {candidate_round_id}"
    )


# Minimum interviewer character count to consider a voice feedback session
# meaningful. Below this we treat the session as an error so the prior
# feedback (if any) is preserved and the Lambda is not triggered on a
# bot-greeting-only transcript.
MIN_INTERVIEWER_CHARS = 50


def count_interviewer_chars(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = (msg.get("content") or "").strip()
        total += len(content)
    return total


async def complete_fallback_feedback_session(
    candidate_round_id: str,
    voice_session_token: str,
    transcript: str,
    status: str,
    error_reason: str | None = None,
) -> bool:
    """POST the final transcript + status to backend's internal endpoint.

    Returns True only when the backend acknowledged success. Returns False
    for: missing config, exhausted retries, transport errors, or a backend
    success=False response (e.g. stale-superseded). The caller (`_end_session`)
    uses the return value to drive a token-scoped fallback error write so
    the row never silently sits in `active`.
    """
    settings = get_settings()
    if not settings.internal_api_secret:
        logger.error(
            "internal_api_secret not configured — cannot complete fallback feedback session"
        )
        return False
    url = f"{settings.backend_url.rstrip('/')}/api/v2/internal/feedback/voice-complete"
    headers = {
        "X-Internal-Secret": settings.internal_api_secret,
        "Content-Type": "application/json",
    }
    payload = {
        "candidate_round_id": candidate_round_id,
        "voice_session_token": voice_session_token,
        "transcript": transcript,
        "status": status,
        "error_reason": error_reason,
    }
    client = await _get_http_client()
    for attempt in range(2):
        try:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in (200, 201, 204):
                try:
                    body = resp.json()
                    if isinstance(body, dict) and body.get("success") is False:
                        # Backend rejected as stale/superseded — return True so
                        # the caller does NOT try to write its own terminal
                        # status (that would overwrite the new owner's row).
                        logger.warning(
                            f"Fallback feedback voice-complete rejected as stale "
                            f"(reason={body.get('reason')})"
                        )
                        return True
                except Exception:
                    pass
                logger.info(
                    f"Fallback feedback session reported to backend "
                    f"({status}, {len(transcript)} chars)"
                )
                return True
            logger.error(
                f"Fallback feedback voice-complete attempt {attempt+1} failed: "
                f"{resp.status_code} {resp.text[:300]}"
            )
        except Exception as e:
            logger.error(f"Fallback feedback voice-complete attempt {attempt+1} error: {e}")
        if attempt == 0:
            await asyncio.sleep(2)
    return False


async def terminal_fallback_feedback_voice_error(
    candidate_round_id: str, voice_session_token: str, error_reason: str
):
    """Write `error` status directly to candidate_rounds, scoped by token.

    Used when the backend internal endpoint is unreachable. Constrained by
    both token and a non-terminal status so a superseded session cannot
    clobber the new owner's row.
    """
    client = await _get_http_client()
    headers = {**_get_headers(), "Prefer": "return=representation"}
    resp = await client.patch(
        _rest_url("candidate_rounds"),
        headers=headers,
        params={
            "id": f"eq.{candidate_round_id}",
            "feedback_voice_session_token": f"eq.{voice_session_token}",
            "feedback_voice_session_status": "in.(pending,active)",
        },
        json={
            "feedback_voice_session_status": "error",
            "feedback_voice_session_token": None,
            "feedback_voice_session_error": (error_reason or "unknown")[:500],
        },
    )
    if resp.status_code not in (200, 204):
        logger.error(
            f"Terminal error fallback update failed: {resp.status_code} {resp.text[:200]}"
        )
        return
    rows = resp.json() if resp.text else []
    if not rows:
        logger.info(
            f"Terminal error fallback ignored (row already moved on) for "
            f"candidate_round {candidate_round_id}"
        )
    else:
        logger.warning(
            f"Terminal error fallback applied for candidate_round {candidate_round_id}: "
            f"{error_reason}"
        )


async def _run_fallback_feedback_pipeline(
    connection, candidate_round_id: str, voice_session_token: str
):
    setup_start = asyncio.get_event_loop().time()

    role_context, scorecard = await fetch_role_and_scorecard(candidate_round_id)
    if role_context and scorecard:
        persona_text = generate_persona(role_context, scorecard)
    else:
        persona_text = (
            "You are mayzul, a friendly recruiter coordinator collecting interview feedback. "
            "Ask the interviewer how the interview went, what stood out, and their overall recommendation. "
            "Keep responses concise -- 1-2 sentences. "
            "When you have enough feedback, thank the interviewer and say goodbye. End your final message with [END]."
        )

    settings = get_settings()
    rtvi = RTVIProcessor()
    # Append-only transcript record — the shared `messages` list gets compacted
    # in place by context summarization, so end-of-call counting/formatting must
    # NOT read from it (a long feedback call would be misread as near-empty).
    transcript_recorder = TranscriptAccumulatorProcessor()
    config = PipelineConfig(
        deepgram_api_key=settings.voice_deepgram_api_key,
        llm_api_key=settings.litellm_master_key,
        llm_model=settings.voice_feedback_model,
        llm_base_url=settings.llm_gateway_url + "/v1",
        tts_voice=settings.voice_tts_voice,
        persona_text=persona_text,
        max_context_tokens=settings.max_context_tokens,
        target_context_tokens=settings.target_context_tokens,
        max_unsummarized_messages=settings.max_unsummarized_messages,
        min_messages_after_summary=settings.min_messages_after_summary,
        flux_eot_threshold=settings.flux_eot_threshold,
        flux_eager_eot_threshold=settings.flux_eager_eot_threshold,
        flux_eot_timeout_ms=settings.flux_eot_timeout_ms,
        rtvi_processor=rtvi,
        transcript_accumulator=transcript_recorder,
    )

    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )

    end_event = asyncio.Event()
    session_ended = asyncio.Event()
    pipeline, messages = PipelineFactory.create_pipeline(config, transport, end_event)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            allow_interruptions=True,
        ),
        observers=[RTVIObserver(rtvi)],
    )

    session_start_time: float | None = None

    async def _end_session(reason: str):
        if session_ended.is_set():
            return
        session_ended.set()
        session_duration_ms = int((asyncio.get_event_loop().time() - setup_start) * 1000)

        transcript_text = ""
        interviewer_chars = 0
        try:
            # The recorder survives context-summarization compaction; `messages`
            # does not. Fall back to it only if no turn was ever recorded.
            turns = transcript_recorder.turns or messages
            transcript_text = format_conversation_transcript(turns)
            interviewer_chars = count_interviewer_chars(turns)
        except Exception as e:
            logger.error(f"Failed to format fallback feedback transcript: {e}")

        logger.info("voice_session_end", extra={
            "event": "voice_session_end",
            "candidate_round_id": candidate_round_id,
            "reason": reason,
            "session_type": "fallback_feedback",
            "session_duration_ms": session_duration_ms,
            "interviewer_chars": interviewer_chars,
        })

        elapsed = (asyncio.get_event_loop().time() - session_start_time) if session_start_time else 0
        if reason == "client_disconnected" and elapsed < 5 and interviewer_chars == 0:
            logger.info(
                f"Instant fallback feedback disconnect ({elapsed:.1f}s, no interviewer speech) "
                f"— resetting to pending for retry"
            )
            await update_fallback_feedback_voice_status(
                candidate_round_id, voice_session_token, "pending"
            )
            return

        # Bot-only transcripts (interviewer never spoke, or said almost nothing)
        # must NOT be persisted as completed feedback. Otherwise a user who just
        # heard the greeting and disconnected could overwrite the row's existing
        # feedback with a bot-only transcript and trigger a useless Lambda run.
        if interviewer_chars < MIN_INTERVIEWER_CHARS:
            final_status = "error"
            error_reason = (
                f"insufficient_interviewer_content:{interviewer_chars}chars:{reason}"
            )
            transcript_to_send = ""
        else:
            final_status = "completed"
            error_reason = None
            transcript_to_send = transcript_text

        ok = False
        try:
            ok = await complete_fallback_feedback_session(
                candidate_round_id,
                voice_session_token,
                transcript_to_send,
                final_status,
                error_reason,
            )
        except Exception as e:
            logger.error(f"complete_fallback_feedback_session raised: {e}")
            ok = False

        if not ok:
            # Backend unreachable / config missing / retries exhausted. Mark the
            # row as error directly so it can never be silently stuck in `active`.
            # Token-scoped so a superseded session cannot clobber the row.
            await terminal_fallback_feedback_voice_error(
                candidate_round_id,
                voice_session_token,
                error_reason or f"voice_complete_unreachable:{reason}",
            )

    async def _watch_end_event():
        await end_event.wait()
        logger.info("Fallback feedback end marker detected, queueing EndFrame")
        await task.queue_frames([EndFrame()])
        await asyncio.sleep(8)
        if not session_ended.is_set():
            logger.warning("Fallback feedback EndFrame safety timeout (8s) — force cancelling")
            await _end_session("conversation_complete")
            await task.cancel()

    async def _session_timer():
        await asyncio.sleep(FALLBACK_FEEDBACK_WRAPUP_WARNING_SECS)
        if session_ended.is_set():
            return
        logger.info("Fallback feedback session approaching time limit, injecting wrap-up")
        messages.append({
            "role": "system",
            "content": (
                "You are running low on time. Wrap up NOW. If you have covered most scorecard topics, "
                "thank the interviewer and say goodbye. End your message with [END]."
            ),
        })
        await task.queue_frames([LLMRunFrame()])
        await asyncio.sleep(FALLBACK_FEEDBACK_SESSION_TIMEOUT_SECS - FALLBACK_FEEDBACK_WRAPUP_WARNING_SECS)
        if session_ended.is_set():
            return
        logger.info("Fallback feedback hard time limit reached")
        try:
            await task.queue_frames([
                TTSSpeakFrame(
                    text="Thanks so much for sharing your feedback. I have everything I need. Have a great day!",
                    append_to_context=False,
                )
            ])
            await asyncio.sleep(4)
        except Exception:
            pass
        await _end_session("time_limit")
        await task.cancel()

    bg_tasks: list[asyncio.Task] = []
    greeting_sent = False

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        nonlocal session_start_time, greeting_sent
        if greeting_sent:
            logger.warning("Fallback feedback on_client_connected fired again, skipping duplicate greeting")
            return
        greeting_sent = True
        session_start_time = asyncio.get_event_loop().time()
        setup_ms = int((session_start_time - setup_start) * 1000)
        logger.info("voice_session_start", extra={
            "event": "voice_session_start",
            "candidate_round_id": candidate_round_id,
            "session_type": "fallback_feedback",
            "setup_ms": setup_ms,
        })
        # NOTE: status was already transitioned pending -> active by the
        # offer handler's atomic claim. No need to write it again here.
        messages.append({
            "role": "system",
            "content": (
                "Say a brief hello, state that you're collecting interview feedback, "
                "and immediately ask about the first scorecard topic. Keep it to 2 sentences."
            ),
        })
        await task.queue_frames([LLMRunFrame()])
        bg_tasks.append(asyncio.create_task(_watch_end_event()))
        bg_tasks.append(asyncio.create_task(_session_timer()))

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Fallback feedback client disconnected for candidate_round {candidate_round_id}")
        await _end_session("client_disconnected")
        await task.cancel()

    @task.event_handler("on_pipeline_error")
    async def on_pipeline_error(task, frame: ErrorFrame):
        logger.error("voice_pipeline_error", extra={
            "event": "voice_pipeline_error",
            "candidate_round_id": candidate_round_id,
            "session_type": "fallback_feedback",
            "error": str(frame.error),
            "fatal": frame.fatal,
        }, exc_info=frame.exception)
        if frame.fatal:
            await update_fallback_feedback_voice_status(
                candidate_round_id, voice_session_token, "error"
            )
            msg = ERROR_MESSAGES["fatal"]
        else:
            msg = ERROR_MESSAGES["default"]
        try:
            await task.queue_frames([TTSSpeakFrame(text=msg, append_to_context=False)])
        except Exception as e:
            logger.error(f"Failed to speak fallback feedback error message: {e}")

    runner = PipelineRunner(handle_sigint=False)
    logger.info(f"Fallback feedback voice pipeline starting for candidate_round {candidate_round_id}")
    try:
        await runner.run(task)
    except Exception as e:
        logger.error(f"Fallback feedback voice pipeline error for {candidate_round_id}: {e}")
        await update_fallback_feedback_voice_status(
            candidate_round_id, voice_session_token, "error"
        )
    finally:
        for t in bg_tasks:
            t.cancel()
        if end_event.is_set() and not session_ended.is_set():
            logger.info("Fallback feedback pipeline flushed after EndFrame, waiting 1.5s")
            await asyncio.sleep(1.5)
            await _end_session("conversation_complete")
        elif not session_ended.is_set():
            await _end_session("unknown")
        logger.info(f"Fallback feedback voice pipeline completed for {candidate_round_id}")


@app.post("/api/offer/feedback/{session_token}")
async def fallback_feedback_offer(
    session_token: str, request: Request, background_tasks: BackgroundTasks
):
    candidate_round = await validate_fallback_feedback_session_token(session_token)
    if not candidate_round:
        raise HTTPException(
            status_code=403, detail="Invalid or expired feedback session token"
        )

    stored_token = str(candidate_round.get("feedback_voice_session_token", ""))
    if not secrets.compare_digest(session_token, stored_token):
        raise HTTPException(status_code=403, detail="Token mismatch")

    candidate_round_id = candidate_round["id"]

    # Ensure this token's session is 'active' (idempotent): claims pending->active
    # on the first offer, and accepts re-offers that are already 'active' so the
    # pipecat client can renegotiate/reconnect mid-call without being 403'd.
    claimed = await claim_fallback_feedback_session(candidate_round_id, session_token)
    if not claimed:
        # A live re-offer of THIS session is accepted (status pending|active).
        # Reaching here means the token no longer matches (a newer session
        # superseded this one) or the row is terminal.
        raise HTTPException(
            status_code=409,
            detail="This voice feedback session is no longer active. Please refresh and start again.",
        )

    body = await request.json()
    sdp_request = SmallWebRTCRequest(
        sdp=body["sdp"],
        type=body["type"],
        pc_id=body.get("pc_id"),
        restart_pc=body.get("restart_pc"),
        request_data=body.get("request_data"),
    )

    async def on_connection(connection):
        background_tasks.add_task(
            _run_fallback_feedback_pipeline,
            connection,
            candidate_round_id,
            session_token,
        )

    answer = await _webrtc_handler.handle_web_request(sdp_request, on_connection)
    return answer


@app.patch("/api/offer/feedback/{session_token}")
async def ice_candidate_fallback_feedback(session_token: str, request: Request):
    body = await request.json()
    patch_request = SmallWebRTCPatchRequest(
        pc_id=body["pc_id"],
        candidates=[IceCandidate(**c) for c in body.get("candidates", [])],
    )
    await _webrtc_handler.handle_patch_request(patch_request)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Screening interview voice mode. HYBRID: the v2-intake dynamic-prompt/tools
# machinery (per-turn prompt refresh + mark_question_covered tool) plus the
# fallback-feedback token validation + end-of-session backend POST. Pinned to
# candidate_rounds.screening_voice_session_token. Mirrors:
#   - validate/claim/complete: validate_fallback_feedback_session_token et al.
#   - dynamic prompt + tools:   _run_v2_intake_pipeline
# Transcript is accumulated in `messages` and POSTed at end — we NEVER write
# transcripts.segments here (Task 9 persists + triggers scoring backend-side).
# ---------------------------------------------------------------------------

SCREENING_SESSION_TIMEOUT_SECS = 1800
SCREENING_WRAPUP_WARNING_SECS = 1770

# Max time a pending screening voice token may sit before treated as stale.
SCREENING_TOKEN_TTL_SECS = 3600

# Stable speaker name for the agent's turns in the screening transcript.
SCREENING_AGENT_SPEAKER = "Scout Interviewer"
SCREENING_CANDIDATE_SPEAKER = "Candidate"


def format_screening_transcript(messages: list[dict]) -> str:
    """Speaker-attributed transcript: candidate (user) vs the agent (assistant).

    Distinct from format_conversation_transcript (feedback flow), where the human
    is the interviewer. In screening the human is the candidate, so labels flip.
    """
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content or role == "system":
            continue
        if not isinstance(content, str):
            continue
        content = content.replace("[END]", "")
        content = content.replace("[interrupted — user only heard partial response]", "")
        content = normalize_phonetic_name(content)
        content = content.strip()
        if not content:
            continue
        speaker = SCREENING_AGENT_SPEAKER if role == "assistant" else SCREENING_CANDIDATE_SPEAKER
        lines.append(f"{speaker}: {content}")
    return "\n\n".join(lines)


async def validate_screening_session_token(session_token: str) -> dict | None:
    client = await _get_http_client()
    resp = await client.get(
        _rest_url("candidate_rounds"),
        headers=_get_headers(),
        params={
            "select": (
                "id,round_id,screening_voice_session_token,"
                "screening_voice_session_status,screening_voice_session_started_at"
            ),
            "screening_voice_session_token": f"eq.{session_token}",
        },
    )
    if resp.status_code != 200:
        logger.error(f"Supabase screening query failed: {resp.status_code} {resp.text}")
        return None
    data = resp.json()
    if not data:
        logger.warning(f"Screening session token not found in DB: {session_token[:8]}...")
        return None
    record = data[0]
    status = record.get("screening_voice_session_status")
    # Accept BOTH the first offer (pending) and re-offers of an already-claimed
    # session (active) — pipecat renegotiates/reconnects mid-call. Only terminal
    # states (completed/error) are non-claimable. The token (minted fresh per
    # /start-voice) is the real two-tab guard. Mirrors the fallback-feedback path.
    if status not in ("pending", "active"):
        logger.info(
            f"Screening session for candidate_round {record['id']} not claimable "
            f"(status={status}); rejecting offer."
        )
        return None
    started_at_str = record.get("screening_voice_session_started_at")
    if started_at_str:
        try:
            started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - started_at).total_seconds()
            if age > SCREENING_TOKEN_TTL_SECS:
                logger.warning(
                    f"Screening token for candidate_round {record['id']} expired "
                    f"({age:.0f}s > {SCREENING_TOKEN_TTL_SECS}s); rejecting."
                )
                return None
        except ValueError:
            pass
    logger.info(f"Screening session validated for candidate_round {record['id']}")
    return record


async def claim_screening_session(candidate_round_id: str, session_token: str) -> bool:
    """CAS pending->active for this exact token (idempotent on active re-offers).

    Mirrors claim_fallback_feedback_session: constrained by id + token + status
    IN (pending, active). Returns False only when terminal or the token no longer
    matches (a newer session superseded this one)."""
    client = await _get_http_client()
    headers = {**_get_headers(), "Prefer": "return=representation"}
    resp = await client.patch(
        _rest_url("candidate_rounds"),
        headers=headers,
        params={
            "id": f"eq.{candidate_round_id}",
            "screening_voice_session_token": f"eq.{session_token}",
            "screening_voice_session_status": "in.(pending,active)",
        },
        json={"screening_voice_session_status": "active"},
    )
    if resp.status_code not in (200, 204):
        logger.error(f"Claim of screening session failed: {resp.status_code} {resp.text}")
        return False
    rows = resp.json() if resp.text else []
    if not rows:
        logger.info(
            f"Screening claim lost for candidate_round {candidate_round_id} "
            f"(another offer already active or row terminal)"
        )
        return False
    return True


async def update_screening_voice_status(
    candidate_round_id: str, voice_session_token: str, voice_status: str
):
    """Token-scoped status update (no-op if the row was superseded)."""
    client = await _get_http_client()
    headers = {**_get_headers(), "Prefer": "return=representation"}
    resp = await client.patch(
        _rest_url("candidate_rounds"),
        headers=headers,
        params={
            "id": f"eq.{candidate_round_id}",
            "screening_voice_session_token": f"eq.{voice_session_token}",
            "screening_voice_session_status": "in.(pending,active)",
        },
        json={"screening_voice_session_status": voice_status},
    )
    if resp.status_code not in (200, 204):
        logger.error(
            f"Failed to update screening voice status to '{voice_status}': "
            f"{resp.status_code} {resp.text}"
        )


async def complete_screening_session(
    candidate_round_id: str,
    voice_session_token: str,
    transcript: str,
    status: str,
    error_reason: str | None = None,
) -> bool:
    """POST the final transcript + status to the backend's internal endpoint.

    Same payload shape as complete_fallback_feedback_session — the backend
    (Task 9) persists the transcript + triggers screening scoring. Returns True
    only when the backend acknowledged success."""
    settings = get_settings()
    if not settings.internal_api_secret:
        logger.error(
            "internal_api_secret not configured — cannot complete screening session"
        )
        return False
    url = f"{settings.backend_url.rstrip('/')}/api/v2/internal/screening/voice-complete"
    headers = {
        "X-Internal-Secret": settings.internal_api_secret,
        "Content-Type": "application/json",
    }
    payload = {
        "candidate_round_id": candidate_round_id,
        "voice_session_token": voice_session_token,
        "transcript": transcript,
        "status": status,
        "error_reason": error_reason,
    }
    client = await _get_http_client()
    for attempt in range(2):
        try:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in (200, 201, 204):
                try:
                    body = resp.json()
                    if isinstance(body, dict) and body.get("success") is False:
                        logger.warning(
                            f"Screening voice-complete rejected as stale "
                            f"(reason={body.get('reason')})"
                        )
                        return True
                except Exception:
                    pass
                logger.info(
                    f"Screening session reported to backend ({status}, {len(transcript)} chars)"
                )
                return True
            logger.error(
                f"Screening voice-complete attempt {attempt+1} failed: "
                f"{resp.status_code} {resp.text[:300]}"
            )
        except Exception as e:
            logger.error(f"Screening voice-complete attempt {attempt+1} error: {e}")
        if attempt == 0:
            await asyncio.sleep(2)
    return False


async def terminal_screening_voice_error(
    candidate_round_id: str, voice_session_token: str, error_reason: str
):
    """Write `error` directly to candidate_rounds when the backend is unreachable.

    Token + non-terminal-status scoped so a superseded session can't clobber the
    new owner's row. Mirrors terminal_fallback_feedback_voice_error."""
    client = await _get_http_client()
    headers = {**_get_headers(), "Prefer": "return=representation"}
    resp = await client.patch(
        _rest_url("candidate_rounds"),
        headers=headers,
        params={
            "id": f"eq.{candidate_round_id}",
            "screening_voice_session_token": f"eq.{voice_session_token}",
            "screening_voice_session_status": "in.(pending,active)",
        },
        json={
            "screening_voice_session_status": "error",
            "screening_voice_session_token": None,
            "screening_voice_session_error": (error_reason or "unknown")[:500],
        },
    )
    if resp.status_code not in (200, 204):
        logger.error(
            f"Terminal screening error update failed: {resp.status_code} {resp.text[:200]}"
        )


async def load_screening_config_for_round(round_id: str) -> tuple[dict | None, list[dict]]:
    """Load the round's screening config + ordered question snapshot.

    Returns (config_row, snapshot_questions). config_row carries `voice` and
    `persona_snapshot`. Returns (None, []) on missing config or query failure."""
    client = await _get_http_client()
    resp = await client.get(
        _rest_url("round_screening_configs"),
        headers=_get_headers(),
        params={
            "select": (
                "id,voice,persona_snapshot,"
                "round_screening_questions(id,order_index,title,prompt,probe,signal,dimension,duration_minutes)"
            ),
            "round_id": f"eq.{round_id}",
        },
    )
    if resp.status_code != 200 or not resp.json():
        logger.error(
            f"Failed to load screening config for round {round_id}: "
            f"status={resp.status_code}, body={resp.text[:200]}"
        )
        return None, []
    config_row = resp.json()[0]
    rows = config_row.get("round_screening_questions") or []
    return config_row, snapshot_questions(rows)


def compose_screening_role_context(role_context: RoleContext | None) -> str:
    """Compact role string from the requisition (same source the backend uses)."""
    if role_context is None:
        return "A screening interview for an open role."
    parts = [f"Role: {role_context.role_title}".strip()]
    if role_context.experience_range:
        parts.append(f"Experience: {role_context.experience_range}")
    if role_context.must_have_skills:
        parts.append("Must-have skills: " + ", ".join(role_context.must_have_skills))
    if role_context.good_to_have_skills:
        parts.append("Good-to-have skills: " + ", ".join(role_context.good_to_have_skills))
    return "\n".join(p for p in parts if p)


async def _run_v2_screening_pipeline(
    connection,
    candidate_round_id: str,
    voice_session_token: str,
    config_row: dict,
    questions: list[dict],
    role_context_text: str,
):
    """Run one screening voice session.

    Dynamic per-turn prompt (build_voice_screening_prompt over an in-memory
    `session` dict whose `answered` is mutated by the mark_question_covered tool),
    the screening TTS voice from config, a stable agent speaker name in the
    transcript, and an end-of-session POST to the backend (Task 9)."""
    setup_start = asyncio.get_event_loop().time()
    settings = get_settings()

    # In-memory session: the prompt refresher + tool dispatch both read/mutate it.
    session = {
        "persona_snapshot": config_row.get("persona_snapshot"),
        "questions": questions,
        "role_context": role_context_text,
        "answered": [],
    }

    def _refresh_screening_prompt(messages: list[dict]) -> None:
        prompt = build_voice_screening_prompt(session)
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = prompt
        else:
            messages.insert(0, {"role": "system", "content": prompt})

    def _dispatch_screening_tool(name: str, args: dict, _idx: int) -> dict:
        if name == "mark_question_covered":
            return handle_mark_question_covered(session, args.get("question_id", ""))
        return {"ok": False, "error": f"unknown tool {name}"}

    # Append-only transcript record — the shared `messages` list gets compacted
    # in place by context summarization, so end-of-call counting/formatting must
    # NOT read from it (a long interview would be misread as near-empty).
    transcript_recorder = TranscriptAccumulatorProcessor()

    config = PipelineConfig(
        deepgram_api_key=settings.voice_deepgram_api_key,
        llm_api_key=settings.litellm_master_key,
        llm_model=settings.voice_screening_model,
        llm_base_url=settings.llm_gateway_url + "/v1",
        tts_voice=config_row.get("voice") or settings.voice_tts_voice,
        persona_text=build_voice_screening_prompt(session),
        max_context_tokens=settings.max_context_tokens,
        target_context_tokens=settings.target_context_tokens,
        max_unsummarized_messages=settings.max_unsummarized_messages,
        min_messages_after_summary=settings.min_messages_after_summary,
        flux_eot_threshold=settings.flux_eot_threshold,
        flux_eager_eot_threshold=settings.flux_eager_eot_threshold,
        flux_eot_timeout_ms=settings.flux_eot_timeout_ms,
        tools=ALL_SCREENING_TOOLS,
        intake_tool_dispatch=_dispatch_screening_tool,
        prompt_refresh=_refresh_screening_prompt,
        transcript_accumulator=transcript_recorder,
    )

    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )

    end_event = asyncio.Event()
    session_ended = asyncio.Event()
    pipeline, messages = PipelineFactory.create_pipeline(config, transport, end_event)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            allow_interruptions=True,
        ),
    )

    session_start_time: float | None = None

    async def _end_session(reason: str):
        if session_ended.is_set():
            return
        session_ended.set()
        session_duration_ms = int((asyncio.get_event_loop().time() - setup_start) * 1000)

        transcript_text = ""
        candidate_chars = 0
        try:
            # The recorder survives context-summarization compaction; `messages`
            # does not. Fall back to it only if no turn was ever recorded.
            turns = transcript_recorder.turns or messages
            transcript_text = format_screening_transcript(turns)
            candidate_chars = count_interviewer_chars(turns)  # counts user (=candidate) turns
        except Exception as e:
            logger.error(f"Failed to format screening transcript: {e}")

        logger.info("voice_session_end", extra={
            "event": "voice_session_end",
            "candidate_round_id": candidate_round_id,
            "reason": reason,
            "session_type": "screening",
            "session_duration_ms": session_duration_ms,
            "candidate_chars": candidate_chars,
        })

        elapsed = (asyncio.get_event_loop().time() - session_start_time) if session_start_time else 0
        if reason == "client_disconnected" and elapsed < 5 and candidate_chars == 0:
            logger.info(
                f"Instant screening disconnect ({elapsed:.1f}s, no candidate speech) "
                f"— resetting to pending for retry"
            )
            await update_screening_voice_status(candidate_round_id, voice_session_token, "pending")
            return

        if candidate_chars < MIN_INTERVIEWER_CHARS:
            final_status = "error"
            error_reason = f"insufficient_candidate_content:{candidate_chars}chars:{reason}"
            transcript_to_send = ""
        else:
            final_status = "completed"
            error_reason = None
            transcript_to_send = transcript_text

        ok = False
        try:
            ok = await complete_screening_session(
                candidate_round_id,
                voice_session_token,
                transcript_to_send,
                final_status,
                error_reason,
            )
        except Exception as e:
            logger.error(f"complete_screening_session raised: {e}")
            ok = False

        if not ok:
            await terminal_screening_voice_error(
                candidate_round_id,
                voice_session_token,
                error_reason or f"voice_complete_unreachable:{reason}",
            )

    async def _watch_end_event():
        await end_event.wait()
        logger.info("Screening end marker detected, queueing EndFrame")
        await task.queue_frames([EndFrame()])
        await asyncio.sleep(8)
        if not session_ended.is_set():
            logger.warning("Screening EndFrame safety timeout (8s) — force cancelling")
            await _end_session("conversation_complete")
            await task.cancel()

    async def _session_timer():
        await asyncio.sleep(SCREENING_WRAPUP_WARNING_SECS)
        if session_ended.is_set():
            return
        logger.info("Screening session approaching time limit, injecting wrap-up")
        messages.append({
            "role": "system",
            "content": (
                "You are running low on time. Wrap up NOW. Cover any remaining must-ask "
                "question briefly, then thank the candidate and say goodbye. End your message with [END]."
            ),
        })
        await task.queue_frames([LLMRunFrame()])
        await asyncio.sleep(SCREENING_SESSION_TIMEOUT_SECS - SCREENING_WRAPUP_WARNING_SECS)
        if session_ended.is_set():
            return
        try:
            await task.queue_frames([
                TTSSpeakFrame(
                    text="Thank you so much for your time today. That's everything I needed. Have a great day!",
                    append_to_context=False,
                )
            ])
            await asyncio.sleep(4)
        except Exception:
            pass
        await _end_session("time_limit")
        await task.cancel()

    bg_tasks: list[asyncio.Task] = []
    greeting_sent = False

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        nonlocal session_start_time, greeting_sent
        if greeting_sent:
            logger.warning("Screening on_client_connected fired again, skipping duplicate greeting")
            return
        greeting_sent = True
        session_start_time = asyncio.get_event_loop().time()
        setup_ms = int((session_start_time - setup_start) * 1000)
        logger.info("voice_session_start", extra={
            "event": "voice_session_start",
            "candidate_round_id": candidate_round_id,
            "session_type": "screening",
            "setup_ms": setup_ms,
        })
        # status was already pending -> active by the offer handler's atomic claim.
        messages.append({
            "role": "system",
            "content": (
                "Greet the candidate warmly, introduce yourself as their screening "
                "interviewer, and ask the first uncovered question. Keep it to 2 sentences."
            ),
        })
        await task.queue_frames([LLMRunFrame()])
        bg_tasks.append(asyncio.create_task(_watch_end_event()))
        bg_tasks.append(asyncio.create_task(_session_timer()))

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Screening client disconnected for candidate_round {candidate_round_id}")
        await _end_session("client_disconnected")
        await task.cancel()

    @task.event_handler("on_pipeline_error")
    async def on_pipeline_error(task, frame: ErrorFrame):
        logger.error("voice_pipeline_error", extra={
            "event": "voice_pipeline_error",
            "candidate_round_id": candidate_round_id,
            "session_type": "screening",
            "error": str(frame.error),
            "fatal": frame.fatal,
        }, exc_info=frame.exception)
        if frame.fatal:
            await update_screening_voice_status(candidate_round_id, voice_session_token, "error")
            msg = ERROR_MESSAGES["fatal"]
        else:
            msg = ERROR_MESSAGES["default"]
        try:
            await task.queue_frames([TTSSpeakFrame(text=msg, append_to_context=False)])
        except Exception as e:
            logger.error(f"Failed to speak screening error message: {e}")

    runner = PipelineRunner(handle_sigint=False)
    logger.info(f"Screening voice pipeline starting for candidate_round {candidate_round_id}")
    try:
        await runner.run(task)
    except Exception as e:
        logger.error(f"Screening voice pipeline error for {candidate_round_id}: {e}")
        await update_screening_voice_status(candidate_round_id, voice_session_token, "error")
    finally:
        for t in bg_tasks:
            t.cancel()
        if end_event.is_set() and not session_ended.is_set():
            logger.info("Screening pipeline flushed after EndFrame, waiting 1.5s")
            await asyncio.sleep(1.5)
            await _end_session("conversation_complete")
        elif not session_ended.is_set():
            await _end_session("unknown")
        logger.info(f"Screening voice pipeline completed for {candidate_round_id}")


@app.post("/api/offer/screening/{session_token}")
async def screening_offer(
    session_token: str, request: Request, background_tasks: BackgroundTasks
):
    candidate_round = await validate_screening_session_token(session_token)
    if not candidate_round:
        raise HTTPException(
            status_code=403, detail="Invalid or expired screening session token"
        )

    stored_token = str(candidate_round.get("screening_voice_session_token", ""))
    if not secrets.compare_digest(session_token, stored_token):
        raise HTTPException(status_code=403, detail="Token mismatch")

    candidate_round_id = candidate_round["id"]
    round_id = candidate_round.get("round_id")
    if not round_id:
        raise HTTPException(status_code=409, detail="Screening round not configured")

    config_row, questions = await load_screening_config_for_round(round_id)
    if config_row is None or not questions:
        raise HTTPException(status_code=409, detail="Screening is not configured for this round")

    claimed = await claim_screening_session(candidate_round_id, session_token)
    if not claimed:
        raise HTTPException(
            status_code=409,
            detail="This screening session is no longer active. Please refresh and start again.",
        )

    role_context, _scorecard = await fetch_role_and_scorecard(candidate_round_id)
    role_context_text = compose_screening_role_context(role_context)

    body = await request.json()
    sdp_request = SmallWebRTCRequest(
        sdp=body["sdp"],
        type=body["type"],
        pc_id=body.get("pc_id"),
        restart_pc=body.get("restart_pc"),
        request_data=body.get("request_data"),
    )

    async def on_connection(connection):
        background_tasks.add_task(
            _run_v2_screening_pipeline,
            connection,
            candidate_round_id,
            session_token,
            config_row,
            questions,
            role_context_text,
        )

    answer = await _webrtc_handler.handle_web_request(sdp_request, on_connection)
    return answer


@app.patch("/api/offer/screening/{session_token}")
async def ice_candidate_screening(session_token: str, request: Request):
    body = await request.json()
    patch_request = SmallWebRTCPatchRequest(
        pc_id=body["pc_id"],
        candidates=[IceCandidate(**c) for c in body.get("candidates", [])],
    )
    await _webrtc_handler.handle_patch_request(patch_request)
    return {"status": "ok"}


@app.post("/v2/intake/offer")
async def v2_intake_offer(request: Request, background_tasks: BackgroundTasks):
    """v2 intake voice session start.

    Body: {"session_id": "<uuid>", "sdp": "...", "type": "offer"}
    Returns: WebRTC answer or {"status": "rejected", "reason": "..."}.

    Reads the intake_sessions row, seeds LLMContext with formatted turns,
    builds the dynamic system prompt, binds intake-core tools, installs the
    TurnPersistFrameProcessor + a coverage-tracker hook, and runs the Pipecat
    pipeline until [END] or hangup.
    """
    body = await request.json()
    # The pipecat SmallWebRTCTransport client sends only {sdp,type,pc_id} in the
    # body, so the frontend passes the session via the URL query string. Accept
    # either (body for the legacy backend-proxy path, query for the direct
    # pipecat-client path).
    session_id = body.get("session_id") or request.query_params.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="missing session_id")

    settings = get_settings()

    from supabase import create_client
    sb = create_client(settings.supabase_url, settings.supabase_secret_key)

    try:
        session_row = load_intake_session_for_voice(sb, session_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="session not found")

    if session_row.get("active_modality") not in (None, "voice"):
        return {"status": "rejected", "reason": "another modality is currently active"}

    sb.table("intake_sessions").update({
        "active_modality": "voice",
        "status": "active",
    }).eq("id", session_id).execute()

    system_prompt = build_voice_intake_prompt(session_row)
    seed_messages = format_turns_for_llm(session_row.get("turns") or [])

    # The coverage tracker runs through the LiteLLM gateway (phase 3). `llm_core`
    # is imported here rather than at module scope because `get_client()`
    # constructs its HTTP client on first call, and this module is imported by
    # tooling that has no gateway configured.
    from llm_core import get_client as get_llm_client

    tracker_llm = get_llm_client()
    tracker_model_ref = "voice-intake"   # a gateway alias, not a provider model id

    config = PipelineConfig(
        deepgram_api_key=settings.voice_deepgram_api_key,
        llm_api_key=settings.litellm_master_key,
        llm_model=settings.voice_intake_model,
        llm_base_url=settings.llm_gateway_url + "/v1",
        tts_voice=settings.voice_tts_voice,
        persona_text=system_prompt,
        max_context_tokens=settings.max_context_tokens,
        target_context_tokens=settings.target_context_tokens,
        max_unsummarized_messages=settings.max_unsummarized_messages,
        min_messages_after_summary=settings.min_messages_after_summary,
        flux_eot_threshold=settings.flux_eot_threshold,
        flux_eager_eot_threshold=settings.flux_eager_eot_threshold,
        flux_eot_timeout_ms=settings.flux_eot_timeout_ms,
        seed_messages=seed_messages,
        tools=INTAKE_TOOLS,
        intake_session_id=session_id,
        intake_supabase_client=sb,
        intake_tool_dispatch=lambda name, args, idx: dispatch_tool_call(
            client=sb, session_id=session_id, tool_name=name, tool_args=args, turn_idx=idx,
        ),
        intake_on_user_turn=lambda text, idx: run_coverage_tracker(
            supabase_client=sb,
            llm=tracker_llm,
            model=tracker_model_ref,
            session_id=session_id,
            last_user_turn=text,
        ),
        intake_initial_turn_idx=len(session_row.get("turns") or []),
    )

    sdp_request = SmallWebRTCRequest(
        sdp=body["sdp"],
        type=body["type"],
        pc_id=body.get("pc_id"),
        restart_pc=body.get("restart_pc"),
        request_data=body.get("request_data"),
    )

    async def _on_connection(connection):
        background_tasks.add_task(
            _run_v2_intake_pipeline,
            connection,
            config,
            session_id,
            sb,
        )

    answer = await _webrtc_handler.handle_web_request(sdp_request, _on_connection)
    return answer


async def _run_v2_intake_pipeline(connection, config: PipelineConfig, session_id: str, sb):
    """Run the v2 intake pipeline for one voice session."""
    session_ended = asyncio.Event()
    end_event = asyncio.Event()

    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    pipeline, messages = PipelineFactory.create_pipeline(config, transport, end_event)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            allow_interruptions=True,
        ),
    )

    intake_session_registry.register(session_id=session_id, task=task)

    setup_start = asyncio.get_event_loop().time()

    async def _end_session(reason: str):
        if session_ended.is_set():
            return
        session_ended.set()
        logger.info("v2_intake_session_end", extra={
            "event": "v2_intake_session_end",
            "session_id": session_id,
            "reason": reason,
        })
        update_payload: dict = {"active_modality": None}
        if reason == "conversation_complete":
            update_payload["status"] = "ready"
        try:
            # Sync Supabase .execute() blocks the shared asyncio loop (aiortc
            # media runs on it) — offload so a slow teardown DB round-trip can't
            # stall other live voice sessions.
            await asyncio.to_thread(
                lambda: sb.table("intake_sessions")
                .update(update_payload)
                .eq("id", session_id)
                .execute()
            )
        except Exception as ex:
            logger.warning("v2_clear_modality_failed", session_id=session_id, error=str(ex))
        # The gateway client is deliberately NOT closed here. It was a per-session
        # AsyncAnthropic before phase 3; llm_core.get_client() returns a PROCESS
        # SINGLETON, so closing it at the end of one voice session would tear down
        # the transport every later session in this worker depends on.

    async def _watch_end_event():
        await end_event.wait()
        logger.info("v2 intake end marker detected, queueing EndFrame")
        await task.queue_frames([EndFrame()])
        await asyncio.sleep(8)
        if not session_ended.is_set():
            logger.warning("v2 intake EndFrame safety timeout (8s) — force cancelling")
            await _end_session("conversation_complete")
            await task.cancel()

    async def _session_timer():
        timeout = int(os.getenv("INTAKE_V2_VOICE_SESSION_TIMEOUT_SECS", "1800"))
        wrapup = timeout - 30
        await asyncio.sleep(wrapup)
        if session_ended.is_set():
            return
        logger.info("v2 intake session approaching time limit, injecting wrap-up")
        messages.append({
            "role": "system",
            "content": "You are running low on time. Wrap up NOW. Thank the recruiter and say goodbye. End your message with [END].",
        })
        await task.queue_frames([LLMRunFrame()])
        await asyncio.sleep(timeout - wrapup)
        if session_ended.is_set():
            return
        try:
            await task.queue_frames([
                TTSSpeakFrame(text="Thanks so much for your time. I have everything I need. Have a wonderful day!", append_to_context=False)
            ])
            await asyncio.sleep(4)
        except Exception:
            pass
        await _end_session("time_limit")
        await task.cancel()

    bg_tasks: list[asyncio.Task] = []
    greeting_sent = False

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        nonlocal greeting_sent
        if greeting_sent:
            logger.warning("v2 on_client_connected fired again, skipping duplicate greeting")
            return
        greeting_sent = True
        setup_ms = int((asyncio.get_event_loop().time() - setup_start) * 1000)
        resuming = bool(config.seed_messages)
        logger.info("v2_intake_session_start", extra={
            "event": "v2_intake_session_start",
            "session_id": session_id,
            "setup_ms": setup_ms,
            "resuming": resuming,
        })
        # On a FRESH session, open with the greeting. On a RESUMED session
        # (prior text/voice turns already in context), greeting again makes the
        # agent restart the conversation ("let me start over") and lose the
        # thread. Instead, nudge it to pick up exactly where it left off.
        if resuming:
            nudge = (
                "You are resuming this same intake conversation on voice — the full "
                "history above is yours. Do NOT greet, reintroduce yourself, apologize, "
                "or restart. In at most one short sentence, continue naturally from the "
                "last thing that was said and move on to the next topic you still need to cover."
            )
        else:
            nudge = "Say your brief, warm opening greeting as instructed in your persona. One to two sentences only."
        messages.append({"role": "system", "content": nudge})
        await task.queue_frames([LLMRunFrame()])
        bg_tasks.append(asyncio.create_task(_watch_end_event()))
        bg_tasks.append(asyncio.create_task(_session_timer()))

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"v2 intake voice client disconnected for session {session_id}")
        intake_session_registry.unregister(session_id)
        await _end_session("client_disconnected")
        await task.cancel()

    @task.event_handler("on_pipeline_error")
    async def on_pipeline_error(task, frame: ErrorFrame):
        logger.error("v2_pipeline_error", extra={
            "event": "v2_pipeline_error",
            "session_id": session_id,
            "error": str(frame.error),
            "fatal": frame.fatal,
        }, exc_info=frame.exception)
        msg = ERROR_MESSAGES["fatal"] if frame.fatal else ERROR_MESSAGES["default"]
        try:
            await task.queue_frames([TTSSpeakFrame(text=msg, append_to_context=False)])
        except Exception as e:
            logger.error(f"Failed to speak v2 error message: {e}")

    runner = PipelineRunner(handle_sigint=False)
    logger.info(f"v2 intake voice pipeline starting for session {session_id}")
    try:
        await runner.run(task)
    except Exception as e:
        logger.error(f"v2 intake voice pipeline error for session {session_id}: {e}")
    finally:
        intake_session_registry.unregister(session_id)
        for t in bg_tasks:
            t.cancel()
        if end_event.is_set() and not session_ended.is_set():
            logger.info("v2 intake pipeline flushed after EndFrame, waiting 1.5s")
            await asyncio.sleep(1.5)
            await _end_session("conversation_complete")
        elif not session_ended.is_set():
            await _end_session("unknown")
        logger.info(f"v2 intake voice pipeline completed for session {session_id}")


@app.patch("/v2/intake/offer")
async def v2_intake_ice_candidate(request: Request):
    body = await request.json()
    # The pipecat client sets pc_id from the offer ANSWER; if a trickle batch
    # flushes before the answer is applied, this.pc_id is undefined and
    # JSON.stringify drops the key entirely → body["pc_id"] used to KeyError →
    # 500 on every ICE candidate → the browser's candidates never reach us →
    # no inbound media → no transcript. Don't crash: ack-and-skip when pc_id is
    # absent (SDP-embedded host candidates still connect, esp. on localhost),
    # and route normally when it's present so trickle works off-localhost too.
    pc_id = body.get("pc_id") or request.query_params.get("pc_id")
    if not pc_id:
        logger.warning(f"v2 ICE candidate without pc_id; skipping (keys={list(body.keys())})")
        return {"status": "ignored", "reason": "no pc_id"}
    patch_request = SmallWebRTCPatchRequest(
        pc_id=pc_id,
        candidates=[IceCandidate(**c) for c in body.get("candidates", [])],
    )
    await _webrtc_handler.handle_patch_request(patch_request)
    return {"status": "ok"}


@app.post("/internal/sessions/{session_id}/drain")
async def internal_drain_session(session_id: str, request: Request):
    """Backend asks us to gracefully drain the active Pipecat session for this id.
    Authenticated via X-Internal-Secret. Returns 404 if no session is registered
    (treated as success/no-op by the backend caller — see VoiceAgentClient)."""
    _verify_internal_secret(request)
    try:
        result = await _drain_session(
            registry=intake_session_registry,
            session_id=session_id,
            safety_timeout_s=DEFAULT_SAFETY_TIMEOUT_S,
        )
    except SessionNotFound:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=404,
            content={"detail": "no active session", "session_id": session_id},
        )
    return result


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("src.main:app", host="0.0.0.0", port=settings.service_port, log_level="info")
