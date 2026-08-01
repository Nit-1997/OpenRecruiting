from functools import lru_cache
from typing import Any
import json
import re

import httpx

from src.config import get_settings
from src.logging import get_logger

logger = get_logger(__name__)

_async_client: httpx.AsyncClient | None = None
PARTIAL_MIN_INTERVIEWER_TURNS = 1
PARTIAL_MIN_INTERVIEWER_CHARS = 150
_INTERVIEWER_LINE_RE = re.compile(r"^interviewer\s*:\s*(.+)$", re.IGNORECASE)
_BOT_SPEAKER_NAMES = {"scout", "scout ai", "scout interview assistant"}


def get_async_http_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None or _async_client.is_closed:
        _async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _async_client


def _extract_interviewer_metrics_from_feedback_transcript(
    feedback_transcript: str | None,
) -> tuple[int, int]:
    if not isinstance(feedback_transcript, str) or not feedback_transcript.strip():
        return 0, 0

    turns = 0
    chars = 0
    for raw_line in feedback_transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _INTERVIEWER_LINE_RE.match(line)
        if not match:
            continue
        content = match.group(1).strip()
        if not content:
            continue
        turns += 1
        chars += len(content)
    return turns, chars


def _extract_relative_word_timestamp(word: dict) -> float | None:
    start_ts = word.get("start_timestamp")
    if isinstance(start_ts, dict):
        rel = start_ts.get("relative")
        if isinstance(rel, (int, float)):
            return float(rel)
        return None
    if isinstance(start_ts, (int, float)):
        return float(start_ts)
    return None


def _extract_segment_speaker(segment: dict) -> str:
    participant = segment.get("participant") or {}
    speaker = ""
    if isinstance(participant, dict):
        speaker = participant.get("name") or participant.get("display_name") or ""
    if not speaker:
        raw_speaker = segment.get("speaker") or segment.get("speaker_name")
        if isinstance(raw_speaker, dict):
            speaker = raw_speaker.get("name") or raw_speaker.get("display_name") or ""
        elif isinstance(raw_speaker, str):
            speaker = raw_speaker
    return str(speaker).strip().lower()


def _extract_segment_timestamp(segment: dict) -> float | None:
    start_ts = segment.get("start_timestamp")
    if isinstance(start_ts, dict):
        rel = start_ts.get("relative")
        if isinstance(rel, (int, float)):
            return float(rel)
        return None
    if isinstance(start_ts, (int, float)):
        return float(start_ts)
    alt = segment.get("start")
    if isinstance(alt, (int, float)):
        return float(alt)
    return None


def _extract_interviewer_metrics_from_segments(
    segments: list[dict] | str | None,
    feedback_start_seconds: float | None,
    exclude_speakers: set[str] | None = None,
) -> tuple[int, int]:
    if isinstance(segments, str):
        try:
            segments = json.loads(segments)
        except Exception:
            return 0, 0

    if not isinstance(segments, list):
        return 0, 0

    if feedback_start_seconds is None:
        total = len(segments)
        if total == 0:
            return 0, 0
        segments = segments[max(0, int(total * 0.8)):]

    turns = 0
    chars = 0

    for segment in segments:
        if not isinstance(segment, dict):
            continue

        speaker = _extract_segment_speaker(segment)
        skip_names = _BOT_SPEAKER_NAMES | (exclude_speakers or set())
        if not speaker or speaker in skip_names:
            continue

        words = segment.get("words")
        text = ""
        if isinstance(words, list) and words:
            parts: list[str] = []
            for word in words:
                if not isinstance(word, dict):
                    continue
                token = word.get("text")
                if not isinstance(token, str):
                    continue
                token = token.strip()
                if not token:
                    continue
                if feedback_start_seconds is not None:
                    ts = _extract_relative_word_timestamp(word)
                    if ts is None or ts < feedback_start_seconds:
                        continue
                parts.append(token)
            text = " ".join(parts).strip()
        else:
            raw_text = segment.get("text")
            if isinstance(raw_text, str):
                if feedback_start_seconds is not None:
                    seg_ts = _extract_segment_timestamp(segment)
                    if seg_ts is None or seg_ts < feedback_start_seconds:
                        continue
                text = raw_text.strip()

        if not text:
            continue
        turns += 1
        chars += len(text)

    return turns, chars


def _feedback_start_offset_seconds(
    feedback_started_at: str | None,
    joined_at: str | None,
) -> float | None:
    if not feedback_started_at or not joined_at:
        return None
    try:
        from dateutil import parser
        feedback_dt = parser.isoparse(feedback_started_at)
        joined_dt = parser.isoparse(joined_at)
        return (feedback_dt - joined_dt).total_seconds()
    except Exception:
        return None


class SupabaseClient:
    def __init__(self):
        settings = get_settings()
        self.url = settings.supabase_url
        self.headers = {
            "apikey": settings.supabase_secret_key,
            "Authorization": f"Bearer {settings.supabase_secret_key}",
            "Content-Type": "application/json",
        }

    async def get_feedback_source(
        self, candidate_round_id: str
    ) -> dict:
        """
        Determine whether feedback was captured by the bot or submitted manually.

        Priority: scorecard (manual submission) > bot > none.
        Scorecard takes priority because if an interviewer explicitly submitted
        feedback via the fallback form, that should be used even if the bot
        also captured feedback (which may have been insufficient).
        """
        client = get_async_http_client()

        has_transcript = await self._check_transcript_exists(candidate_round_id)

        cr_resp = await client.get(
            f"{self.url}/rest/v1/candidate_rounds",
            params={
                "id": f"eq.{candidate_round_id}",
                "select": "scorecard_transcript,candidates(name)",
            },
            headers=self.headers,
        )
        cr_data = cr_resp.json()
        scorecard_text = cr_data[0].get("scorecard_transcript") if cr_data else None
        candidate_name = ""
        if cr_data:
            candidate_name = (cr_data[0].get("candidates") or {}).get("name", "")
        candidate_exclude = {candidate_name.strip().lower()} if candidate_name.strip() else set()

        if scorecard_text and scorecard_text.strip():
            logger.info(
                "feedback_source_scorecard",
                candidate_round_id=candidate_round_id,
                scorecard_len=len(scorecard_text),
                has_interview_transcript=has_transcript,
            )
            return {
                "source": "scorecard",
                "scorecard_transcript": scorecard_text,
                "has_interview_transcript": has_transcript,
            }

        bot_resp = await client.get(
            f"{self.url}/rest/v1/recall_bots",
            params={
                "candidate_round_id": f"eq.{candidate_round_id}",
                "select": "feedback_status,feedback_started_at,joined_at",
                "order": "created_at.desc",
            },
            headers=self.headers,
        )
        bot_data = bot_resp.json() or []

        statuses = [b.get("feedback_status") for b in bot_data]
        bot_captured = False

        if any(status in ("completed", "partial", "collecting", "voice_active") for status in statuses):
            context_bot = next(
                (b for b in bot_data if b.get("feedback_status") == "completed"),
                next(
                    (b for b in bot_data if b.get("feedback_status") == "partial"),
                    next(
                        (b for b in bot_data if b.get("feedback_status") in ("collecting", "voice_active")),
                        {},
                    ),
                ),
            )
            feedback_start_seconds = _feedback_start_offset_seconds(
                context_bot.get("feedback_started_at"),
                context_bot.get("joined_at"),
            )

            transcript_resp = await client.get(
                f"{self.url}/rest/v1/transcripts",
                params={
                    "candidate_round_id": f"eq.{candidate_round_id}",
                    "select": "feedback_transcript,segments",
                },
                headers=self.headers,
            )
            transcript_data = transcript_resp.json() or []
            transcript_row = transcript_data[0] if transcript_data else {}
            feedback_transcript = transcript_row.get("feedback_transcript")
            segments = transcript_row.get("segments")

            transcript_available = isinstance(feedback_transcript, str) and bool(feedback_transcript.strip())
            source = "feedback_transcript"
            if transcript_available:
                turns, chars = _extract_interviewer_metrics_from_feedback_transcript(
                    feedback_transcript
                )
                if turns == 0:
                    source = "segments_secondary"
                    turns, chars = _extract_interviewer_metrics_from_segments(
                        segments,
                        feedback_start_seconds,
                        candidate_exclude,
                    )
            else:
                source = "segments_fallback"
                turns, chars = _extract_interviewer_metrics_from_segments(
                    segments,
                    feedback_start_seconds,
                    candidate_exclude,
                )

            bot_captured = (
                turns >= PARTIAL_MIN_INTERVIEWER_TURNS
                and chars >= PARTIAL_MIN_INTERVIEWER_CHARS
            )
            logger.info(
                "feedback_source_content_check",
                candidate_round_id=candidate_round_id,
                source=source,
                turns=turns,
                chars=chars,
                ready=bot_captured,
            )

        logger.info(
            "feedback_source_bots_check",
            candidate_round_id=candidate_round_id,
            bot_count=len(bot_data),
            statuses=statuses,
            bot_captured=bot_captured,
        )

        if bot_captured:
            return {"source": "bot"}

        logger.warning(
            "feedback_source_none",
            candidate_round_id=candidate_round_id,
            has_interview_transcript=has_transcript,
        )
        return {"source": "none", "has_interview_transcript": has_transcript}

    async def _check_transcript_exists(self, candidate_round_id: str) -> bool:
        client = get_async_http_client()
        resp = await client.get(
            f"{self.url}/rest/v1/transcripts",
            params={
                "candidate_round_id": f"eq.{candidate_round_id}",
                "select": "segments,feedback_transcript",
            },
            headers=self.headers,
        )
        data = resp.json()
        if not data:
            return False
        raw_seg = data[0].get("segments")
        feedback_transcript = data[0].get("feedback_transcript")
        if isinstance(feedback_transcript, str) and len(feedback_transcript.strip()) > 10:
            return True
        return bool(raw_seg and (
            (isinstance(raw_seg, list) and len(raw_seg) > 0) or
            (isinstance(raw_seg, str) and len(raw_seg) > 10)
        ))

    async def get_transcript_data(
        self, candidate_round_id: str
    ) -> tuple[list[dict] | None, float | None]:
        """
        Get transcript segments and feedback start timestamp.

        If segments are not in DB, attempts to fetch from transcript_url (Recall).
        """
        client = get_async_http_client()

        # First, get recall_bot data (includes transcript_url as fallback)
        bot_resp = await client.get(
            f"{self.url}/rest/v1/recall_bots",
            params={
                "candidate_round_id": f"eq.{candidate_round_id}",
                "select": "feedback_started_at,joined_at,transcript_url,recall_bot_id",
            },
            headers=self.headers,
        )
        bot_data = bot_resp.json()
        bot_record = bot_data[0] if bot_data else {}
        logger.info(
            "recall_bot_data",
            candidate_round_id=candidate_round_id,
            has_bot=bool(bot_record),
            transcript_url=bot_record.get("transcript_url", "N/A")[:100] if bot_record.get("transcript_url") else None,
            recall_bot_id=bot_record.get("recall_bot_id"),
        )

        # Get transcript from DB
        transcript_resp = await client.get(
            f"{self.url}/rest/v1/transcripts",
            params={
                "candidate_round_id": f"eq.{candidate_round_id}",
                "select": "segments,raw_transcript_url",
            },
            headers=self.headers,
        )
        transcript_data = transcript_resp.json()
        segments = None
        transcript_url = None

        if transcript_data:
            raw_segments = transcript_data[0].get("segments")
            transcript_url = transcript_data[0].get("raw_transcript_url")

            if raw_segments:
                if isinstance(raw_segments, list) and len(raw_segments) > 0:
                    segments = raw_segments
                elif isinstance(raw_segments, str):
                    import json
                    try:
                        parsed = json.loads(raw_segments)
                        if isinstance(parsed, list) and len(parsed) > 0:
                            segments = parsed
                        else:
                            logger.warning(
                                "segments_not_valid_list",
                                candidate_round_id=candidate_round_id,
                                raw_type=type(raw_segments).__name__,
                                first_50_chars=raw_segments[:50] if isinstance(raw_segments, str) else str(raw_segments)[:50],
                            )
                    except json.JSONDecodeError:
                        logger.warning(
                            "segments_not_valid_json",
                            candidate_round_id=candidate_round_id,
                            first_50_chars=raw_segments[:50],
                        )
                else:
                    logger.warning(
                        "segments_unexpected_type",
                        candidate_round_id=candidate_round_id,
                        segments_type=type(raw_segments).__name__,
                    )

        logger.info(
            "transcript_data_check",
            candidate_round_id=candidate_round_id,
            has_segments=segments is not None,
            raw_transcript_url=transcript_url[:100] if transcript_url else None,
            bot_transcript_url=bot_record.get("transcript_url", "")[:100] if bot_record.get("transcript_url") else None,
        )

        # If no valid segments in DB but we have a transcript_url, try to fetch directly
        if not segments and (transcript_url or bot_record.get("transcript_url")):
            url_to_fetch = transcript_url or bot_record.get("transcript_url")
            logger.info(
                "fetching_transcript_from_url",
                candidate_round_id=candidate_round_id,
                transcript_url=url_to_fetch[:100] if url_to_fetch else None,
            )
            try:
                resp = await client.get(url_to_fetch, timeout=60.0)
                if resp.status_code == 200:
                    segments = resp.json()
                    logger.info(
                        "fetched_transcript_from_url",
                        candidate_round_id=candidate_round_id,
                        segments_count=len(segments) if segments else 0,
                    )
                    # Store in DB for future use
                    await self._store_transcript(candidate_round_id, segments, url_to_fetch)
            except Exception as e:
                logger.error(
                    "failed_to_fetch_transcript_from_url",
                    candidate_round_id=candidate_round_id,
                    error=str(e),
                )
        elif not segments and bot_record.get("recall_bot_id"):
            recall_bot_id = bot_record.get("recall_bot_id")
            logger.info(
                "trying_recall_api",
                candidate_round_id=candidate_round_id,
                recall_bot_id=recall_bot_id,
            )
            segments = await self._fetch_from_recall_api(recall_bot_id, candidate_round_id)
        elif not segments:
            logger.warning(
                "no_transcript_url_available",
                candidate_round_id=candidate_round_id,
                message="No valid segments and no transcript_url to fetch from",
            )

        # Calculate feedback_start_timestamp
        feedback_start_timestamp = None
        if bot_record.get("feedback_started_at") and bot_record.get("joined_at"):
            try:
                from dateutil import parser
                feedback_dt = parser.isoparse(bot_record["feedback_started_at"])
                joined_dt = parser.isoparse(bot_record["joined_at"])
                feedback_start_timestamp = (feedback_dt - joined_dt).total_seconds()
            except Exception as e:
                logger.warning(
                    "failed_to_parse_timestamps",
                    candidate_round_id=candidate_round_id,
                    error=str(e),
                )

        logger.info(
            "fetched_transcript",
            candidate_round_id=candidate_round_id,
            segments_count=len(segments) if segments else 0,
            has_feedback_timestamp=feedback_start_timestamp is not None,
        )
        return segments, feedback_start_timestamp

    async def _fetch_from_recall_api(
        self, recall_bot_id: str, candidate_round_id: str
    ) -> list[dict] | None:
        """
        Fetch transcript from Recall API using the bot ID.

        Gets the bot info which includes recording URLs, then fetches the transcript.
        """
        settings = get_settings()
        if not settings.recall_api_key:
            logger.warning("recall_api_key_not_configured")
            return None

        client = get_async_http_client()
        try:
            bot_resp = await client.get(
                f"{settings.recall_base_url}/bot/{recall_bot_id}",
                headers={"Authorization": f"Token {settings.recall_api_key}"},
                timeout=30.0,
            )
            if bot_resp.status_code != 200:
                logger.warning(
                    "recall_api_bot_fetch_failed",
                    recall_bot_id=recall_bot_id,
                    status_code=bot_resp.status_code,
                )
                return None

            bot_data = bot_resp.json()
            recordings = bot_data.get("recordings", [])
            if not recordings:
                logger.warning("recall_api_no_recordings", recall_bot_id=recall_bot_id)
                return None

            media = recordings[0].get("media_shortcuts", {})
            transcript_url = media.get("transcript", {}).get("data", {}).get("download_url")

            if not transcript_url:
                logger.warning("recall_api_no_transcript_url", recall_bot_id=recall_bot_id)
                return None

            logger.info(
                "fetching_transcript_from_recall",
                recall_bot_id=recall_bot_id,
                transcript_url=transcript_url[:100],
            )

            transcript_resp = await client.get(transcript_url, timeout=60.0)
            if transcript_resp.status_code == 200:
                segments = transcript_resp.json()
                logger.info(
                    "fetched_transcript_from_recall",
                    recall_bot_id=recall_bot_id,
                    segments_count=len(segments) if segments else 0,
                )
                if segments:
                    await self._store_transcript(candidate_round_id, segments, transcript_url)
                return segments
            else:
                logger.warning(
                    "recall_transcript_fetch_failed",
                    recall_bot_id=recall_bot_id,
                    status_code=transcript_resp.status_code,
                )
                return None

        except Exception as e:
            logger.error(
                "recall_api_error",
                recall_bot_id=recall_bot_id,
                error=str(e),
            )
            return None

    async def _store_transcript(
        self, candidate_round_id: str, segments: list[dict], transcript_url: str
    ) -> None:
        """Store fetched transcript in DB for future use."""
        client = get_async_http_client()
        from datetime import datetime, timezone

        # Check if transcript record exists
        existing = await client.get(
            f"{self.url}/rest/v1/transcripts",
            params={
                "candidate_round_id": f"eq.{candidate_round_id}",
                "select": "id",
            },
            headers=self.headers,
        )

        transcript_record = {
            "candidate_round_id": candidate_round_id,
            "segments": segments,
            "raw_transcript_url": transcript_url,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

        if existing.json():
            await client.patch(
                f"{self.url}/rest/v1/transcripts",
                params={"candidate_round_id": f"eq.{candidate_round_id}"},
                json=transcript_record,
                headers={**self.headers, "Prefer": "return=representation"},
            )
        else:
            await client.post(
                f"{self.url}/rest/v1/transcripts",
                json=transcript_record,
                headers={**self.headers, "Prefer": "return=representation"},
            )

        logger.info(
            "stored_transcript",
            candidate_round_id=candidate_round_id,
            segments_count=len(segments),
        )

    async def get_scorecard_questions(
        self, candidate_round_id: str
    ) -> tuple[list[dict], dict[int, str]]:
        client = get_async_http_client()

        cr_resp = await client.get(
            f"{self.url}/rest/v1/candidate_rounds",
            params={"id": f"eq.{candidate_round_id}", "select": "round_id"},
            headers=self.headers,
        )
        cr_data = cr_resp.json()
        if not cr_data:
            return [], {}

        round_id = cr_data[0]["round_id"]

        q_resp = await client.get(
            f"{self.url}/rest/v1/feedback_questions",
            params={
                "round_id": f"eq.{round_id}",
                "deleted_at": "is.null",
                "select": "id,question_number,heading,description",
                "order": "question_number.asc",
            },
            headers=self.headers,
        )
        questions = q_resp.json() or []
        questions_map = {q["question_number"]: q["id"] for q in questions}

        logger.info(
            "fetched_scorecard",
            candidate_round_id=candidate_round_id,
            question_count=len(questions),
        )
        return questions, questions_map

    async def get_role_context(self, candidate_round_id: str) -> dict[str, Any]:
        client = get_async_http_client()

        cr_resp = await client.get(
            f"{self.url}/rest/v1/candidate_rounds",
            params={"id": f"eq.{candidate_round_id}", "select": "candidate_id"},
            headers=self.headers,
        )
        if not cr_resp.json():
            return self._default_role_context()

        candidate_id = cr_resp.json()[0]["candidate_id"]

        cand_resp = await client.get(
            f"{self.url}/rest/v1/candidates",
            params={"id": f"eq.{candidate_id}", "select": "requisition_id"},
            headers=self.headers,
        )
        if not cand_resp.json():
            return self._default_role_context()

        requisition_id = cand_resp.json()[0]["requisition_id"]

        req_resp = await client.get(
            f"{self.url}/rest/v1/requisitions",
            params={
                "id": f"eq.{requisition_id}",
                "select": "role_title,role_location,experience_min_years,experience_max_years,"
                "intake_notes,job_description,must_have_skills,good_to_have_skills",
            },
            headers=self.headers,
        )
        if not req_resp.json():
            return self._default_role_context()

        req = req_resp.json()[0]
        exp_min = req.get("experience_min_years", 0)
        exp_max = req.get("experience_max_years")
        seniority = f"{exp_min}-{exp_max} Years" if exp_max else f"{exp_min}+ Years"

        return {
            "role": req.get("role_title") or "Unknown",
            "seniority": seniority,
            "location": req.get("role_location") or "Unknown",
            "must_have_skills": req.get("must_have_skills") or [],
            "good_to_have_skills": req.get("good_to_have_skills") or [],
            "intake_notes": req.get("intake_notes") or "",
            "job_description": req.get("job_description") or "",
        }

    def _default_role_context(self) -> dict[str, Any]:
        return {
            "role": "Unknown",
            "seniority": "Unknown",
            "location": "Unknown",
            "must_have_skills": [],
            "good_to_have_skills": [],
            "intake_notes": "",
            "job_description": "",
        }

    async def update_processing_status(
        self, candidate_round_id: str, status: str, error: str | None = None
    ) -> None:
        client = get_async_http_client()
        from datetime import datetime, timezone

        update_data = {
            "processing_status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        if status == "processing":
            update_data["processing_started_at"] = datetime.now(timezone.utc).isoformat()
        elif status == "completed":
            update_data["processing_completed_at"] = datetime.now(timezone.utc).isoformat()
            update_data["processing_error"] = None
            update_data["status"] = "completed"
            update_data["completed_at"] = datetime.now(timezone.utc).isoformat()
        elif status == "failed":
            update_data["processing_error"] = error

        await client.patch(
            f"{self.url}/rest/v1/candidate_rounds",
            params={"id": f"eq.{candidate_round_id}"},
            json=update_data,
            headers={**self.headers, "Prefer": "return=representation"},
        )
        logger.info(
            "updated_status", candidate_round_id=candidate_round_id, status=status
        )

    async def save_feedback_results(
        self,
        candidate_round_id: str,
        feedback_output: dict,
        questions_map: dict[int, str],
    ) -> int:
        client = get_async_http_client()
        from datetime import datetime, timezone

        rating = feedback_output.get("round_rating", "maybe")
        if rating == "mid":
            rating = "maybe"
        summary = feedback_output.get("round_summary", "")
        question_summaries = feedback_output.get("question_summaries", {})
        competency_snapshots = feedback_output.get("competency_snapshots", "")
        overall_feedback = feedback_output.get("overall_feedback") or []

        question_summaries_str_keys = {str(k): v for k, v in question_summaries.items()} if question_summaries else {}

        logger.info(
            "save_feedback_debug",
            candidate_round_id=candidate_round_id,
            has_question_summaries=bool(question_summaries),
            question_summaries_keys=list(question_summaries_str_keys.keys()) if question_summaries_str_keys else [],
            question_summaries_sample=str(question_summaries_str_keys)[:200] if question_summaries_str_keys else "empty",
            round_summary_len=len(summary),
            rating=rating,
        )

        update_data = {"rating": rating, "summary": summary, "overall_feedback": overall_feedback}
        if question_summaries_str_keys:
            update_data["question_summaries"] = question_summaries_str_keys
        if competency_snapshots:
            update_data["competency_snapshots"] = competency_snapshots

        patch_resp = await client.patch(
            f"{self.url}/rest/v1/candidate_rounds",
            params={"id": f"eq.{candidate_round_id}"},
            json=update_data,
            headers={**self.headers, "Prefer": "return=representation"},
        )

        if patch_resp.status_code not in (200, 201, 204):
            logger.error(
                "patch_candidate_round_failed",
                candidate_round_id=candidate_round_id,
                status_code=patch_resp.status_code,
                response_text=patch_resp.text[:500],
            )
        else:
            patch_data = patch_resp.json() if patch_resp.text else []
            saved_qs = patch_data[0].get("question_summaries") if patch_data else None
            logger.info(
                "patch_candidate_round_success",
                candidate_round_id=candidate_round_id,
                status_code=patch_resp.status_code,
                saved_question_summaries_present=saved_qs is not None,
            )

        existing_resp = await client.get(
            f"{self.url}/rest/v1/candidate_feedback",
            params={
                "candidate_round_id": f"eq.{candidate_round_id}",
                "source": "eq.bot",
                "select": "id,feedback_question_id",
            },
            headers=self.headers,
        )
        existing = existing_resp.json() or []
        old_by_question: dict[str, list[str]] = {}
        for fb in existing:
            fq_id = fb["feedback_question_id"]
            old_by_question.setdefault(fq_id, []).append(fb["id"])

        inserted_count = 0
        questions_with_new: set[str] = set()

        for question in feedback_output.get("feedback_questions", []):
            q_num = question.get("question_number")
            fq_id = questions_map.get(q_num)
            if not fq_id:
                continue

            feedback_entries = question.get("feedback", [])
            if feedback_entries:
                questions_with_new.add(fq_id)

            for entry in feedback_entries:
                now = datetime.now(timezone.utc).isoformat()
                record = {
                    "candidate_round_id": candidate_round_id,
                    "feedback_question_id": fq_id,
                    "feedback_text": entry.get("feedback_data", ""),
                    "evidence": entry.get("evidence", []),
                    "evidence_status": entry.get("evidence_status", "none"),
                    "source": "bot",
                    "created_at": now,
                    "updated_at": now,
                }
                await client.post(
                    f"{self.url}/rest/v1/candidate_feedback",
                    json=record,
                    headers={**self.headers, "Prefer": "return=representation"},
                )
                inserted_count += 1

        ids_to_delete = []
        for fq_id in questions_with_new:
            ids_to_delete.extend(old_by_question.get(fq_id, []))

        for old_id in ids_to_delete:
            await client.delete(
                f"{self.url}/rest/v1/candidate_feedback",
                params={"id": f"eq.{old_id}"},
                headers=self.headers,
            )

        logger.info(
            "saved_feedback",
            candidate_round_id=candidate_round_id,
            inserted=inserted_count,
            deleted=len(ids_to_delete),
        )
        return inserted_count


@lru_cache()
def get_supabase_client() -> SupabaseClient:
    return SupabaseClient()
