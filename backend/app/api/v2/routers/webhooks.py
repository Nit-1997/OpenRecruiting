"""
Recall.ai webhook router.

Two endpoints, mirroring v1's:

  POST /api/v2/webhooks/recall/bot-status (account: bot lifecycle + calendar)
  POST /api/v2/webhooks/recall/realtime   (per-bot: transcript + participants)

Both verify the HMAC signature, parse the envelope, then dispatch to the
appropriate handler module. The router stays thin — all real work lives
in `app.services.recall_webhook.*`.

Why two endpoints? Recall delivers events via two separate channels:
  - the ACCOUNT webhook (configured once in the Recall dashboard) carries bot
    lifecycle events (`bot.joining_call`/`bot.in_call_recording`/`bot.done`/…)
    plus `calendar.*` events → `/bot-status`;
  - per-bot REALTIME endpoints (the URL is written onto each bot at creation
    time) carry high-frequency in-call events (`transcript.data`,
    `participant_events.*`, chat) → `/realtime`.
They are different config locations with different event streams, so they get
different routes. There is intentionally no bare `/webhooks/recall` route — it
was a redundant duplicate of `/bot-status` (same handler) and only added
confusion, so it was removed; the account webhook lives at `/bot-status`.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.config import get_settings
from app.logging_config import correlation_id_var, get_logger
from app.services.recall_webhook import (
    bot_status_handler,
    chat_handler,
    participant_handler,
    signature,
    transcript_handler,
)
from app.services.recall_webhook.constants import EventType


logger = get_logger(__name__)


router = APIRouter(prefix="/webhooks/recall", tags=["v2/webhooks"])


# ---------------------------------------------------------------------------
# Account webhook (/bot-status) — bot lifecycle (bot.*) + calendar.*
# ---------------------------------------------------------------------------


@router.post("/bot-status")
async def handle_recall_bot_status_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Account-level Recall webhook — bot lifecycle (`bot.*`) + `calendar.*`.

    This is the single account webhook, configured once in the Recall dashboard
    (v1 used this same `/bot-status` path). Per-bot, high-frequency in-call
    events (`transcript.data`, `participant_events.*`) are delivered separately
    to `/webhooks/recall/realtime` — that URL is written onto each bot at
    creation time — so there are exactly two endpoints: this one and `/realtime`.

    We handle `bot.*` (bot lifecycle) here. Calendar events (`calendar.*`) are
    routed to the ported calendar-intelligence worker (enqueue a durable sync
    hint + best-effort fast-path dispatch). Anything else is acknowledged with
    `{status: ignored}` so Recall doesn't retry forever.
    """
    if not await _verify_or_test_bypass(request):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    event_type = payload.get("event") or ""
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    if event_type.startswith("bot."):
        # Recall fires GRANULAR bot lifecycle events — bot.joining_call,
        # bot.in_call_recording, bot.done, bot.fatal, ... — each a distinct
        # event type, NOT a single `bot.status_change` envelope. The status
        # code is the event suffix; the bot id is nested at data.bot.id and the
        # sub_code at data.data.sub_code. v1 handled exactly this
        # (legacy .../api/v1/webhooks/recall.py:340-352: `startswith("bot.")`
        # + `event.replace("bot.","")` + `data.bot.id`). The v2 port modelled
        # only the legacy `bot.status_change` shape ({bot_id, status:{code}}), so
        # every real Recall event fell through to "unhandled" and the whole
        # post-interview pipeline (recording fetch, feedback, packet, reminder)
        # never ran. Normalize the granular envelope into the shape
        # handle_bot_status_change expects, then dispatch. A literal
        # `bot.status_change` (if ever sent) already has that shape — pass through.
        if event_type == EventType.BOT_STATUS_CHANGE:
            status_data = data
        else:
            bot_obj = data.get("bot") if isinstance(data.get("bot"), dict) else {}
            inner = data.get("data") if isinstance(data.get("data"), dict) else {}
            status_data = {
                **data,
                "bot_id": bot_obj.get("id") or data.get("bot_id"),
                "status": {
                    "code": event_type[len("bot."):],
                    "sub_code": inner.get("sub_code"),
                },
            }
        bot_id = status_data.get("bot_id")
        if bot_id:
            correlation_id_var.set(f"bot:{bot_id}")
        outcome = await bot_status_handler.handle_bot_status_change(
            _supabase(), status_data, background_tasks,
        )
        if outcome is None:
            return {"status": "ignored", "event": event_type, "reason": "unmapped"}
        return {
            "status": "ok",
            "event": event_type,
            "bot_id": outcome.bot_id,
            "new_status": outcome.db_status,
            "cr_transitioned": outcome.transitioned_cr,
            "recording_fetch_queued": outcome.recording_fetch_enqueued,
            "not_admitted_queued": outcome.not_admitted_enqueued,
        }

    # Calendar events: enqueue a durable sync hint, then best-effort
    # fast-path dispatch the immediate sync pass via the ported worker.
    if event_type.startswith(EventType.CALENDAR_PREFIX):
        from app.workers.calendar_intelligence_worker import (
            enqueue_calendar_sync_hint,
            process_calendar_sync_hint,
        )
        try:
            enqueue_result = await enqueue_calendar_sync_hint(event_type, data)
        except Exception as e:
            logger.error(f"webhook: calendar sync enqueue failed: {e}")
            raise HTTPException(status_code=503, detail="Calendar sync enqueue failed")
        calendar_id = str(enqueue_result.get("calendar_id") or "unknown")
        if enqueue_result.get("hint_dt") is not None and get_settings().CALENDAR_INTELLIGENCE_ENABLED:
            background_tasks.add_task(process_calendar_sync_hint, event_type, data)
        return {"status": "queued", "event": event_type, "calendar_id": calendar_id}

    logger.info(f"webhook: unhandled event {event_type}")
    return {"status": "ignored", "event": event_type}


# ---------------------------------------------------------------------------
# Realtime webhook — participant / transcript / chat
# ---------------------------------------------------------------------------


@router.post("/realtime")
async def handle_realtime_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Realtime events from Recall — participant join/leave, transcript
    data, in-meeting chat. Each is routed to its dedicated handler."""
    if not await _verify_or_test_bypass(request):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    event_type = payload.get("event") or ""
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    bot_info = data.get("bot") or {}
    bot_id = bot_info.get("id") if isinstance(bot_info, dict) else None
    if not bot_id:
        logger.warning(f"realtime: missing bot.id event={event_type}")
        return {"status": "error", "message": "Missing bot_id"}

    correlation_id_var.set(f"bot:{bot_id}")
    logger.info(f"realtime: event={event_type} bot={bot_id}")

    if event_type == EventType.PARTICIPANT_JOIN:
        await participant_handler.handle_participant_join(bot_id, data)
    elif event_type == EventType.PARTICIPANT_LEAVE:
        await participant_handler.handle_participant_leave(bot_id, data, background_tasks)
    elif event_type == EventType.CHAT_MESSAGE:
        await chat_handler.handle_chat_message(bot_id, data, background_tasks)
    elif event_type == EventType.TRANSCRIPT_DATA:
        await transcript_handler.handle_transcript_data(bot_id, data, background_tasks)
    else:
        logger.info(f"realtime: unhandled event {event_type}")
        return {"status": "ignored", "event": event_type}

    return {"status": "ok", "event": event_type, "bot_id": bot_id}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _verify_or_test_bypass(request: Request) -> bool:
    """Verify signature, with a tiny test-mode escape hatch: when ENV=test
    and no signature header is present, accept the request so pytest
    fixtures don't have to mint HMAC signatures.

    Hardening (BE-A4a): the bypass is gated behind an explicit non-prod
    assertion. A misconfigured production deployment that sets ENV=test
    must NOT be able to disable HMAC. If the deployment does not look local,
    we treat ENV=test as misconfiguration, log loudly, and fall through to
    real signature verification instead of bypassing.
    """
    settings = get_settings()
    if settings.ENV == "test" and not request.headers.get("webhook-signature"):
        if _looks_like_production(settings):
            logger.warning(
                "webhook: ENV=test bypass refused — WEBHOOK_BASE_URL is not a "
                "local/tunnel address, so this deployment looks like production. "
                "Falling through to HMAC verification."
            )
        else:
            return True
    return await signature.verify_webhook_signature(request)


# Hosts that mark a development deployment. Anything else is assumed to be
# production. This is deliberately fail-closed: an unrecognised domain keeps
# HMAC verification on, so the ENV=test bypass can never be reached by an
# unfamiliar deployment. Self-hosters serve webhooks from their own domain,
# so an allow-list of dev hosts is the only check that stays correct for
# everyone; matching a single vendor domain would never fire.
_DEV_WEBHOOK_HOSTS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "host.docker.internal",
    ".ngrok.io",
    ".ngrok-free.app",
    ".ngrok.app",
    ".trycloudflare.com",
    ".loca.lt",
)


def _looks_like_production(settings) -> bool:
    """True unless WEBHOOK_BASE_URL is a recognised local or tunnel address."""
    base = (settings.WEBHOOK_BASE_URL or "").lower()
    if not base:
        # Unset means nothing is configured to receive webhooks; treat as
        # production so the bypass stays unreachable.
        return True
    return not any(host in base for host in _DEV_WEBHOOK_HOSTS)


def _supabase():
    # Imported here (not at module top) so test fixtures that monkey-patch
    # get_supabase_admin_client land on the call site.
    from app.services.supabase import get_supabase_admin_client
    return get_supabase_admin_client()
