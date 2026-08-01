import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from uuid import uuid4
from app.config import get_settings
from app.logging_config import correlation_id_var, get_logger, request_id_var
import re

logger = get_logger(__name__)


async def _inject_recall_request_id(request: httpx.Request) -> None:
    """Propagate the inbound request_id (and correlation_id, if present) to
    Recall.ai. Recall echoes request IDs in their support logs — having the
    same UUID across our backend logs and Recall's helps triage.
    """
    rid = request_id_var.get()
    if rid:
        request.headers["X-Request-ID"] = rid
    cid = correlation_id_var.get()
    if cid:
        request.headers["X-Correlation-ID"] = cid


class RecallServiceError(Exception):
    def __init__(self, message: str, status_code: int = None, details: dict = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class RecallService:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.RECALL_API_KEY
        self.base_url = settings.RECALL_BASE_URL
        self.bot_name = settings.RECALL_BOT_NAME
        self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Token {self.api_key}"},
                timeout=30.0,
                event_hooks={"request": [_inject_recall_request_id]},
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _build_transcript_config(self, settings) -> Dict[str, Any]:
        """Build transcript provider configuration based on settings."""
        provider = settings.RECALL_TRANSCRIPT_PROVIDER.lower()
        model = settings.RECALL_TRANSCRIPT_MODEL
        language = settings.RECALL_TRANSCRIPT_LANGUAGE
        word_boost = [w.strip() for w in settings.RECALL_TRANSCRIPT_WORD_BOOST.split(",") if w.strip()]
        use_separate_streams = settings.RECALL_TRANSCRIPT_SEPARATE_STREAMS

        transcript_config = {"provider": {}}

        if provider == "deepgram":
            transcript_config["provider"]["deepgram_streaming"] = {
                "model": model or "nova-2",
                "language": language,
                "smart_format": True,
                "punctuate": True
            }
            if word_boost:
                # Nova-3 uses 'keyterm', older models use 'keywords'
                if model == "nova-3":
                    transcript_config["provider"]["deepgram_streaming"]["keyterm"] = word_boost
                else:
                    transcript_config["provider"]["deepgram_streaming"]["keywords"] = word_boost
            logger.info(f"Recall: Using Deepgram transcription with model: {model or 'nova-2'}")

        elif provider == "assemblyai":
            transcript_config["provider"]["assembly_ai_v3_streaming"] = {}
            if word_boost:
                transcript_config["provider"]["assembly_ai_v3_streaming"]["word_boost"] = word_boost
                transcript_config["provider"]["assembly_ai_v3_streaming"]["boost_param"] = "high"
            logger.info("Recall: Using AssemblyAI transcription")

        else:  # Default to recallai
            transcript_config["provider"]["recallai_streaming"] = {
                "mode": model or "prioritize_accuracy",
                "language_code": language
            }
            logger.info(f"Recall: Using Recall.ai native transcription with mode: {model or 'prioritize_accuracy'}")

        # Add diarization config for better speaker attribution
        if use_separate_streams:
            transcript_config["diarization"] = {
                "use_separate_streams_when_available": True
            }
            logger.debug("Recall: Separate stream diarization enabled")

        return transcript_config

    def _build_recording_config(self, settings) -> Dict[str, Any]:
        """Build recording config including transcript and real-time endpoints."""
        recording_config = {
            "transcript": self._build_transcript_config(settings)
        }

        if settings.WEBHOOK_BASE_URL:
            # `RECALL_REALTIME_WEBHOOK_PATH` controls which backend the
            # bot phones home to. v1 is decommissioned, so the fallback is
            # v2's own realtime handler (`/api/v2/webhooks/recall/realtime`);
            # a v1 path would silently 404 every realtime event. Kept
            # configurable for non-prod overrides — just an env update + restart.
            realtime_path = (
                getattr(settings, "RECALL_REALTIME_WEBHOOK_PATH", "")
                or "/api/v2/webhooks/recall/realtime"
            )
            if not realtime_path.startswith("/"):
                realtime_path = "/" + realtime_path
            realtime_url = f"{settings.WEBHOOK_BASE_URL.rstrip('/')}{realtime_path}"
            recording_config["realtime_endpoints"] = [
                {
                    "type": "webhook",
                    "url": realtime_url,
                    "events": [
                        "participant_events.join",
                        "participant_events.leave",
                        "participant_events.chat_message",
                        "transcript.data"
                    ]
                }
            ]
            logger.info(f"Recall: realtime endpoint set to {realtime_url}")
        else:
            logger.warning("Recall: WEBHOOK_BASE_URL not set, skipping real-time endpoints")

        return recording_config

    def parse_meeting_url(self, url: str) -> Dict[str, str]:
        if 'meet.google.com' in url:
            match = re.search(r'meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})', url)
            if match:
                return {
                    'platform': 'google_meet',
                    'meeting_id': match.group(1),
                    'url': url
                }
            return {'platform': 'google_meet', 'url': url}
        elif 'zoom.us' in url:
            return {'platform': 'zoom', 'url': url}
        elif 'teams.microsoft.com' in url or 'teams.live.com' in url:
            return {'platform': 'microsoft_teams', 'url': url}
        elif 'webex.com' in url:
            return {'platform': 'webex', 'url': url}

        raise RecallServiceError(f"Unsupported meeting platform: {url}")

    async def schedule_bot(
        self,
        meeting_url: str,
        scheduled_at: datetime,
        candidate_name: str,
        candidate_round_id: str
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise RecallServiceError("RECALL_API_KEY not configured")

        settings = get_settings()
        self.parse_meeting_url(meeting_url)

        join_at = scheduled_at - timedelta(seconds=45)

        bot_name = f"{self.bot_name}"

        payload = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "join_at": join_at.isoformat(),

            "automatic_leave": {
                "everyone_left_timeout": {
                    "timeout": settings.RECALL_BOT_EXIT_TIMEOUT,
                    "activate_after": 1
                },
                "waiting_room_timeout": settings.RECALL_BOT_NOONE_JOINED_TIMEOUT,
                "silence_detection": {
                    "timeout": settings.RECALL_BOT_SILENCE_TIMEOUT,
                    "activate_after": 600
                },
                "noone_joined_timeout": settings.RECALL_BOT_NOONE_JOINED_TIMEOUT,
                "in_call_not_recording_timeout": 300
            },

            "recording_config": self._build_recording_config(settings),

            "chat": {
                "on_bot_join": {
                    "send_to": "everyone",
                    "message": "This interview is being recorded by OpenRecruiting for review purposes."
                }
            }
        }

        voice_token = None
        if settings.VOICE_ENABLED and settings.VOICE_AGENT_URL:
            voice_token = str(uuid4())
            payload["output_media"] = {
                "camera": {
                    "kind": "webpage",
                    "config": {"url": f"{settings.VOICE_AGENT_URL}/{voice_token}"}
                }
            }
            payload["variant"] = {
                "zoom": "web_4_core",
                "google_meet": "web_4_core",
                "microsoft_teams": "web_4_core",
            }
            payload["recording_config"]["include_bot_in_recording"] = {
                "audio": True
            }
            logger.info("Recall: Voice agent enabled, added output_media + variant + bot audio in recording")

        try:
            logger.info(f"Recall: Scheduling bot to {meeting_url}")
            logger.debug(f"Recall: Join at: {join_at.isoformat()}")

            response = await self.client.post("/bot", json=payload)
            response.raise_for_status()
            result = response.json()
            if voice_token:
                result["_voice_session_token"] = voice_token
            logger.info(f"Recall: Bot created successfully: {result.get('id')}")
            return result
        except httpx.HTTPStatusError as e:
            error_detail = {}
            try:
                error_detail = e.response.json()
            except Exception:
                error_detail = {"raw": e.response.text}
            logger.error(f"Recall: Error Status: {e.response.status_code}, Details: {error_detail}")
            raise RecallServiceError(
                f"Failed to schedule bot: {e.response.status_code}",
                status_code=e.response.status_code,
                details=error_detail
            )

    async def create_bot_for_intake(
        self,
        meeting_url: str,
        voice_session_token: str | None = None,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise RecallServiceError("RECALL_API_KEY not configured")

        settings = get_settings()
        self.parse_meeting_url(meeting_url)

        payload = {
            "meeting_url": meeting_url,
            "bot_name": f"{self.bot_name}",
            "automatic_leave": {
                "everyone_left_timeout": {
                    "timeout": settings.RECALL_BOT_EXIT_TIMEOUT,
                    "activate_after": 1
                },
                "waiting_room_timeout": settings.RECALL_BOT_NOONE_JOINED_TIMEOUT,
                "noone_joined_timeout": settings.RECALL_BOT_NOONE_JOINED_TIMEOUT,
            },
            "recording_config": self._build_recording_config(settings),
            "chat": {
                "on_bot_join": {
                    "send_to": "everyone",
                    "message": "OpenRecruiting is joining for the intake call."
                }
            },
        }

        if settings.VOICE_ENABLED and settings.VOICE_AGENT_URL and voice_session_token:
            payload["output_media"] = {
                "camera": {
                    "kind": "webpage",
                    "config": {"url": f"{settings.VOICE_AGENT_URL}/{voice_session_token}"}
                }
            }
            payload["variant"] = {
                "zoom": "web_4_core",
                "google_meet": "web_4_core",
                "microsoft_teams": "web_4_core",
            }
            payload["recording_config"]["include_bot_in_recording"] = {"audio": True}

        try:
            logger.info(f"Recall: Creating intake bot for {meeting_url}")
            response = await self.client.post("/bot", json=payload)
            response.raise_for_status()
            result = response.json()
            logger.info(f"Recall: Intake bot created: {result.get('id')}")
            return result
        except httpx.HTTPStatusError as e:
            error_detail = {}
            try:
                error_detail = e.response.json()
            except Exception:
                error_detail = {"raw": e.response.text}
            logger.error(f"Recall: Intake bot error: {e.response.status_code}, Details: {error_detail}")
            raise RecallServiceError(
                f"Failed to create intake bot: {e.response.status_code}",
                status_code=e.response.status_code,
                details=error_detail,
            )

    async def get_bot(self, bot_id: str) -> Dict[str, Any]:
        if not self.api_key:
            raise RecallServiceError("RECALL_API_KEY not configured")

        try:
            response = await self.client.get(f"/bot/{bot_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise RecallServiceError(
                f"Failed to get bot: {e.response.status_code}",
                status_code=e.response.status_code
            )

    async def delete_bot(self, bot_id: str) -> bool:
        if not self.api_key:
            return False

        try:
            response = await self.client.delete(f"/bot/{bot_id}")
            return response.status_code in [200, 204, 404]
        except httpx.HTTPStatusError:
            return False

    async def remove_bot_from_call(self, bot_id: str) -> bool:
        if not self.api_key:
            return False

        try:
            response = await self.client.post(f"/bot/{bot_id}/leave_call")
            return response.status_code in [200, 204]
        except httpx.HTTPStatusError:
            return False

    async def send_chat_message(self, bot_id: str, message: str) -> bool:
        """Send a chat message to the meeting via the bot."""
        if not self.api_key:
            return False

        try:
            response = await self.client.post(
                f"/bot/{bot_id}/send_chat_message",
                json={"to": "everyone", "message": message}
            )
            success = response.status_code in [200, 201]
            if success:
                logger.debug(f"Recall: Chat sent: {message[:50]}...")
            else:
                logger.warning(f"Recall: Chat failed: {response.status_code}")
            return success
        except Exception as e:
            logger.error(f"Recall: Failed to send chat: {e}")
            return False

    async def get_recording_urls(self, bot_id: str) -> Optional[Dict[str, Any]]:
        bot = await self.get_bot(bot_id)
        recordings = bot.get("recordings", [])

        if not recordings:
            return None

        media = recordings[0].get("media_shortcuts", {})

        participant_events = media.get("participant_events", {}).get("data", {})

        return {
            "video_url": media.get("video_mixed", {}).get("data", {}).get("download_url"),
            "video_duration": media.get("video_mixed", {}).get("data", {}).get("duration"),
            "transcript_url": media.get("transcript", {}).get("data", {}).get("download_url"),
            "participants": bot.get("participants", []),
            "participants_download_url": participant_events.get("participants_download_url"),
            "speaker_timeline_url": participant_events.get("speaker_timeline_download_url"),
        }


def get_recall_service() -> RecallService:
    return RecallService()


ACTIVE_BOT_STATUSES = [
    "created", "joining", "in_waiting_room",
    "in_call_not_recording", "in_call_recording",
]
SCHEDULING_LOCK_STALE_SECONDS = 60


async def schedule_or_replace_recall_bot(
    candidate_round_id: str,
    meeting_url: str,
    scheduled_at: datetime,
    candidate_name: str,
) -> dict:
    from app.services.supabase import get_supabase_admin_client
    from fastapi import HTTPException

    supabase = get_supabase_admin_client()
    recall_warning = None

    from datetime import timezone as tz
    now = datetime.now(tz.utc)
    now_iso = now.isoformat()

    lock_result = await supabase.table("candidate_rounds") \
        .update({"scheduling_locked_at": now_iso}) \
        .eq("id", candidate_round_id) \
        .is_("scheduling_locked_at", "null") \
        .execute_async()

    if not lock_result.data:
        row = await supabase.table("candidate_rounds") \
            .select("scheduling_locked_at") \
            .eq("id", candidate_round_id) \
            .execute_async()
        locked_at = row.data[0].get("scheduling_locked_at") if row.data else None
        is_stale = False
        if locked_at:
            try:
                from app.utils import parse_iso_datetime
                locked_time = parse_iso_datetime(locked_at)
                age = (now - locked_time.astimezone(tz.utc)).total_seconds()
                is_stale = age > SCHEDULING_LOCK_STALE_SECONDS
            except (ValueError, TypeError):
                is_stale = True

        if is_stale:
            logger.warning(f"Overriding stale scheduling lock for candidate_round={candidate_round_id}")
            lock_result = await supabase.table("candidate_rounds") \
                .update({"scheduling_locked_at": now_iso}) \
                .eq("id", candidate_round_id) \
                .eq("scheduling_locked_at", locked_at) \
                .execute_async()

    if not lock_result.data:
        raise HTTPException(
            status_code=409,
            detail="Scheduling already in progress for this interview round. Please wait."
        )

    try:
        existing_bots = await supabase.table("recall_bots") \
            .select("id, recall_bot_id, status") \
            .eq("candidate_round_id", candidate_round_id) \
            .in_("status", ACTIVE_BOT_STATUSES) \
            .execute_async()

        if existing_bots.data:
            bots_to_cancel = []
            for bot in existing_bots.data:
                if bot["status"] in ("in_call_recording", "in_call_not_recording"):
                    logger.info(
                        f"Recall: Bot {bot['recall_bot_id']} is in-call — leaving it to finish naturally "
                        f"(candidate_round={candidate_round_id})"
                    )
                else:
                    bots_to_cancel.append(bot)

            if bots_to_cancel:
                recall_service = get_recall_service()
                for bot in bots_to_cancel:
                    bot_status = bot.get("status", "created")
                    # remove_bot_from_call / delete_bot only swallow
                    # httpx.HTTPStatusError internally — a transient
                    # timeout/ConnectError would otherwise propagate out of
                    # this loop and skip the cancelled-in-DB write below.
                    # Catch broadly so a flaky Recall API can't leave the
                    # row stuck in an active status (BE-A4a).
                    try:
                        if bot_status in ("joining", "in_waiting_room"):
                            left = await recall_service.remove_bot_from_call(bot["recall_bot_id"])
                            if not left:
                                logger.warning(
                                    f"Recall: leave_call failed for bot {bot['recall_bot_id']} "
                                    f"(status={bot_status}, candidate_round={candidate_round_id})"
                                )
                        deleted = await recall_service.delete_bot(bot["recall_bot_id"])
                        if not deleted:
                            logger.warning(
                                f"Recall: delete_bot failed for bot {bot['recall_bot_id']} "
                                f"(candidate_round={candidate_round_id}). Marking cancelled in DB anyway."
                            )
                    except Exception as cancel_err:
                        logger.warning(
                            f"Recall: transient error cancelling bot {bot['recall_bot_id']} "
                            f"(candidate_round={candidate_round_id}): {cancel_err}. "
                            f"Marking cancelled in DB anyway."
                        )
                    await supabase.table("recall_bots") \
                        .update({"status": "cancelled"}) \
                        .eq("id", bot["id"]) \
                        .execute_async()
                await recall_service.close()

        recall_service = get_recall_service()
        try:
            bot_response = await recall_service.schedule_bot(
                meeting_url=meeting_url,
                scheduled_at=scheduled_at,
                candidate_name=candidate_name,
                candidate_round_id=candidate_round_id,
            )
            recall_bot_insert = {
                "candidate_round_id": candidate_round_id,
                "recall_bot_id": bot_response["id"],
                "meeting_url": meeting_url,
                "scheduled_at": scheduled_at.isoformat(),
                "status": "created",
                "bot_name": bot_response.get("bot_name", f"Scout - {candidate_name}"),
                "candidate_name": candidate_name,
            }
            voice_token = bot_response.get("_voice_session_token")
            if voice_token:
                recall_bot_insert["voice_session_token"] = voice_token
            await supabase.table("recall_bots").insert(recall_bot_insert).execute_async()
            logger.info(f"Recall bot created for candidate_round {candidate_round_id}")
        except RecallServiceError as e:
            recall_warning = str(e)
            logger.warning(f"Recall bot creation failed: {e}")
        except Exception as e:
            recall_warning = str(e)
            logger.warning(f"Recall bot creation failed: {e}")
        finally:
            await recall_service.close()

    finally:
        await supabase.table("candidate_rounds") \
            .update({"scheduling_locked_at": None}) \
            .eq("id", candidate_round_id) \
            .execute_async()

    return {"recall_warning": recall_warning}
