import json
from datetime import datetime, timezone

from src.clients.supabase import SupabaseClient
from src.logging import get_logger
from src.models import Job, JobStage, JobStatus, RoleContext, TopicInput
from src.parsers import TranscriptParser
from src.services import FeedbackOrchestrator

logger = get_logger(__name__)


def _ensure_segments_list(segments) -> list[dict]:
    """
    Ensure segments is a list of dicts.

    Handles cases where segments might be:
    - A string (JSON serialized)
    - A list of dicts (correct format)
    - None or empty
    """
    if segments is None:
        return []

    if isinstance(segments, str):
        logger.info(f"Segments is string, len={len(segments)}, first_100_chars={repr(segments[:100])}")
        try:
            parsed = json.loads(segments)
            if isinstance(parsed, list):
                logger.info(f"Successfully parsed segments string to list of {len(parsed)} items")
                return parsed
            else:
                logger.warning(f"Parsed segments is not a list: {type(parsed)}")
                return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse segments string as JSON: {e}")
            logger.error(f"Raw string starts with: {repr(segments[:200])}")
            return []

    if isinstance(segments, list):
        return segments

    logger.warning(f"Unexpected segments type: {type(segments)}")
    return []


class JobProcessor:
    def __init__(
        self,
        supabase: SupabaseClient | None = None,
        orchestrator: FeedbackOrchestrator | None = None,
    ):
        self.supabase = supabase
        self.orchestrator = orchestrator or FeedbackOrchestrator()
        self.parser = TranscriptParser()

    async def process(self, job: Job) -> Job:
        logger.info("job_start", job_id=job.id, candidate_round_id=job.candidate_round_id)

        try:
            job.status = JobStatus.PROCESSING
            job.updated_at = datetime.now(timezone.utc)

            stages = list(JobStage)
            start_idx = stages.index(job.current_stage) if job.current_stage else 0

            for stage in stages[start_idx:]:
                job.current_stage = stage
                job = await self._process_stage(job, stage)
                job.updated_at = datetime.now(timezone.utc)

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            logger.info("job_complete", job_id=job.id)

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.retry_count += 1
            job.updated_at = datetime.now(timezone.utc)
            logger.error("job_failed", job_id=job.id, error=str(e))

        return job

    async def _process_stage(self, job: Job, stage: JobStage) -> Job:
        logger.info("stage_start", job_id=job.id, stage=stage.value)

        match stage:
            case JobStage.FETCH_DATA:
                job = await self._fetch_data(job)
            case JobStage.CHUNK_INTERVIEW:
                pass
            case JobStage.MAP_TOPICS:
                pass
            case JobStage.EXTRACT_FEEDBACK:
                pass
            case JobStage.CONDENSE_FEEDBACK:
                pass
            case JobStage.EXTRACT_EVIDENCE:
                pass
            case JobStage.JUDGE_FEEDBACK:
                pass
            case JobStage.PERSIST_RESULTS:
                job = await self._persist_results(job)

        logger.info("stage_complete", job_id=job.id, stage=stage.value)
        return job

    async def _fetch_data(self, job: Job) -> Job:
        if not self.supabase:
            raise ValueError("Supabase client required for fetch_data stage")

        segments, feedback_start_ts = await self.supabase.get_transcript_data(
            job.candidate_round_id
        )
        if not segments:
            raise ValueError("No transcript segments found")

        questions, questions_map = await self.supabase.get_scorecard_questions(
            job.candidate_round_id
        )
        if not questions:
            raise ValueError("No scorecard questions found")

        role_context = await self.supabase.get_role_context(job.candidate_round_id)

        job._raw_data = {
            "segments": segments,
            "feedback_start_timestamp": feedback_start_ts,
            "questions": questions,
            "questions_map": questions_map,
            "role_context": role_context,
        }

        return job

    async def _persist_results(self, job: Job) -> Job:
        if not self.supabase:
            raise ValueError("Supabase client required for persist_results stage")

        if not job.judged_feedback:
            raise ValueError("No judged feedback to persist")

        questions_map = getattr(job, "_raw_data", {}).get("questions_map", {})

        feedback_output = {
            "round_rating": "maybe",
            "round_summary": "",
            "competency_snapshots": "",
            "feedback_questions": [],
        }

        await self.supabase.save_feedback_results(
            job.candidate_round_id, feedback_output, questions_map
        )

        return job

    async def process_from_segments(
        self,
        segments: list[dict],
        feedback_start_timestamp: float | None,
        questions: list[dict],
        role_context: dict | None = None,
    ) -> dict:
        segments = _ensure_segments_list(segments)

        total_words = sum(
            len(s.get("words", [])) if isinstance(s, dict) else 0
            for s in segments
        )
        speakers = list({
            s.get("participant", {}).get("name", "Unknown")
            for s in segments
            if isinstance(s, dict) and "participant" in s
        })
        logger.info(
            "processing_segments",
            segment_count=len(segments),
            total_words=total_words,
            speakers=speakers,
            first_segment_type=type(segments[0]).__name__ if segments else "none",
        )

        full_transcript = self._segments_to_text(segments)

        if not full_transcript.strip():
            raise ValueError("Empty transcript content - no text could be extracted from segments")

        # Split into interview and feedback portions
        if feedback_start_timestamp is not None:
            interview_text = self._segments_to_text(
                segments, end_timestamp=feedback_start_timestamp
            )
            feedback_text = self._segments_to_text(
                segments, start_timestamp=feedback_start_timestamp
            )
            logger.info(
                "transcript_split",
                feedback_start=feedback_start_timestamp,
                interview_len=len(interview_text),
                feedback_len=len(feedback_text),
            )
        else:
            # Fallback: Use 80/20 split (first 80% interview, last 20% feedback)
            # This matches openrecruiting-backend behavior
            last_segment = segments[-1] if segments else {}
            if "words" in last_segment and last_segment.get("words"):
                last_word = last_segment["words"][-1]
                word_ts = last_word.get("start_timestamp", {})
                if isinstance(word_ts, dict):
                    total_duration = word_ts.get("relative", 0)
                else:
                    total_duration = word_ts or 0
            else:
                total_duration = last_segment.get("start_timestamp", 0) or 0

            split_point = total_duration * 0.8
            interview_text = self._segments_to_text(segments, end_timestamp=split_point)
            feedback_text = self._segments_to_text(segments, start_timestamp=split_point)
            logger.warning(
                "no_feedback_timestamp_using_80_20_split",
                total_duration=total_duration,
                split_point=split_point,
            )

        if feedback_start_timestamp is None:
            if not feedback_text.strip():
                feedback_text = full_transcript
                logger.warning("feedback_text_empty_using_full_transcript")
            if not interview_text.strip():
                interview_text = full_transcript
                logger.warning("interview_text_empty_using_full_transcript")
        else:
            if not feedback_text.strip():
                feedback_text = full_transcript
                logger.warning("feedback_text_empty_despite_timestamp_using_full_transcript")
            if not interview_text.strip():
                interview_text = full_transcript
                logger.warning("interview_text_empty_with_timestamp_using_full_transcript")

        logger.info(
            "transcript_ready",
            full_transcript_len=len(full_transcript),
            interview_text_len=len(interview_text),
            feedback_text_len=len(feedback_text),
            interview_word_count=len(interview_text.split()),
            feedback_word_count=len(feedback_text.split()),
        )

        topics = []
        for i, q in enumerate(questions):
            if isinstance(q, str):
                logger.warning(f"Question {i} is a string, not a dict: {q[:50]}")
                continue
            topics.append(
                TopicInput(heading=q["heading"], description=q.get("description", ""))
            )

        role_ctx = None
        if role_context and isinstance(role_context, dict):
            role_ctx = RoleContext(
                role_title=role_context.get("role", "Product Manager"),
                experience_range=role_context.get("seniority", "3-6 years"),
                must_have_skills=role_context.get("must_have_skills", []),
                good_to_have_skills=role_context.get("good_to_have_skills", []),
                job_description=role_context.get("job_description", ""),
                intake_notes=role_context.get("intake_notes", ""),
            )
        elif role_context:
            logger.warning(f"role_context is not a dict: {type(role_context)}")

        complete_result, evidence_result, judge_result, summary_result = (
            await self.orchestrator.process_full_pipeline(
                interview_transcript=interview_text,
                feedback_transcript=feedback_text,
                topics=topics,
                role_context=role_ctx,
                segments=segments,
            )
        )

        return {
            "complete_result": complete_result.model_dump(),
            "evidence_result": evidence_result.model_dump(),
            "judge_result": judge_result.model_dump(),
            "summary_result": summary_result.model_dump(),
        }

    async def process_from_scorecard(
        self,
        scorecard_text: str,
        questions: list[dict],
        role_context: dict | None = None,
        interview_segments: list[dict] | None = None,
    ) -> dict:
        """
        Process feedback from manually submitted scorecard transcript.

        When interview_segments are available (bot recorded the interview but
        didn't capture feedback), uses the Recall transcript as interview_text
        for proper chunking/topic mapping/evidence extraction.
        The scorecard text is always used as feedback_text.
        """
        if not scorecard_text.strip():
            raise ValueError("Empty scorecard transcript")

        feedback_text = scorecard_text

        if interview_segments:
            segments = _ensure_segments_list(interview_segments)
            interview_text = self._segments_to_text(segments)
            logger.info(
                "processing_scorecard_hybrid",
                scorecard_len=len(scorecard_text),
                interview_text_len=len(interview_text),
                segments_count=len(segments),
            )
        else:
            segments = []
            interview_text = scorecard_text
            logger.info(
                "processing_scorecard_only",
                scorecard_len=len(scorecard_text),
                word_count=len(scorecard_text.split()),
            )

        topics = []
        for i, q in enumerate(questions):
            if isinstance(q, str):
                logger.warning(f"Question {i} is a string, not a dict: {q[:50]}")
                continue
            topics.append(
                TopicInput(heading=q["heading"], description=q.get("description", ""))
            )

        role_ctx = None
        if role_context and isinstance(role_context, dict):
            role_ctx = RoleContext(
                role_title=role_context.get("role", "Product Manager"),
                experience_range=role_context.get("seniority", "3-6 years"),
                must_have_skills=role_context.get("must_have_skills", []),
                good_to_have_skills=role_context.get("good_to_have_skills", []),
                job_description=role_context.get("job_description", ""),
                intake_notes=role_context.get("intake_notes", ""),
            )
        elif role_context:
            logger.warning(f"role_context is not a dict: {type(role_context)}")

        logger.info(
            "scorecard_pipeline_input",
            feedback_text_len=len(feedback_text),
            interview_text_len=len(interview_text),
            topic_count=len(topics),
        )

        complete_result, evidence_result, judge_result, summary_result = (
            await self.orchestrator.process_full_pipeline(
                interview_transcript=interview_text,
                feedback_transcript=feedback_text,
                topics=topics,
                role_context=role_ctx,
                segments=segments,
            )
        )

        return {
            "complete_result": complete_result.model_dump(),
            "evidence_result": evidence_result.model_dump(),
            "judge_result": judge_result.model_dump(),
            "summary_result": summary_result.model_dump(),
        }

    def _segments_to_text(
        self,
        segments: list[dict],
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
    ) -> str:
        """
        Convert transcript segments to plain text format.

        Handles two formats (aligned with openrecruiting-backend):
        1. Word-based format: {"words": [...], "participant": {"name": "..."}}
        2. Simple format: {"speaker": "...", "text": "...", "start_timestamp": ...}
        """
        if not segments:
            return ""

        lines = []

        for segment in segments:
            if isinstance(segment, str):
                logger.warning(f"Segment is a string, not a dict: {segment[:50]}")
                continue

            # Format 1: Word-based format (from Recall.ai)
            if "words" in segment:
                words = segment.get("words", [])
                participant = segment.get("participant", {})
                speaker = participant.get("name") or "OpenRecruiting"

                filtered_words = []
                for word in words:
                    word_start = word.get("start_timestamp", {})
                    if isinstance(word_start, dict):
                        timestamp = word_start.get("relative", 0)
                    else:
                        timestamp = word_start or 0

                    if start_timestamp is not None and timestamp < start_timestamp:
                        continue
                    if end_timestamp is not None and timestamp >= end_timestamp:
                        continue

                    filtered_words.append({
                        "text": word.get("text", ""),
                        "timestamp": timestamp
                    })

                if not filtered_words:
                    continue

                # Chunk by sentence boundaries (matching openrecruiting-backend)
                current_chunk = []
                chunk_start = filtered_words[0]["timestamp"]

                for i, word in enumerate(filtered_words):
                    current_chunk.append(word["text"])

                    is_sentence_end = word["text"].rstrip().endswith(('.', '?', '!'))
                    is_last = i == len(filtered_words) - 1
                    chunk_too_long = len(current_chunk) > 50

                    if is_sentence_end or is_last or chunk_too_long:
                        text = " ".join(current_chunk).strip()
                        if text:
                            minutes = int(chunk_start // 60)
                            seconds = int(chunk_start % 60)
                            time_str = f"[{minutes:02d}:{seconds:02d}]"
                            lines.append(f"{time_str} {speaker}: {text}")

                        current_chunk = []
                        if not is_last and i + 1 < len(filtered_words):
                            chunk_start = filtered_words[i + 1]["timestamp"]

            # Format 2: Simple format (speaker + text + start_timestamp)
            else:
                timestamp = segment.get("start_timestamp") or segment.get("start", 0)

                if start_timestamp is not None and timestamp < start_timestamp:
                    continue
                if end_timestamp is not None and timestamp >= end_timestamp:
                    continue

                speaker = segment.get("speaker", "Unknown")
                text = segment.get("text", "").strip()

                if not text:
                    continue

                minutes = int(timestamp // 60)
                seconds = int(timestamp % 60)
                time_str = f"[{minutes:02d}:{seconds:02d}]"

                lines.append(f"{time_str} {speaker}: {text}")

        return "\n\n".join(lines)
