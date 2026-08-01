import asyncio

from src.clients.anthropic import AnthropicClient
from src.logging import get_logger
from src.models import (
    ChunkContent,
    CompleteProcessingResponse,
    EnrichedFeedbackItem,
    EvidenceExtractionResponse,
    FeedbackItem,
    JudgedFeedbackItem,
    JudgeResponse,
    RoleContext,
    SummaryResponse,
    TopicInfo,
    TopicInput,
)
from src.services.evidence import EvidenceService
from src.services.feedback import FeedbackPipeline
from src.services.interview import InterviewPipeline
from src.services.judge import JudgeService
from src.services.summary import SummaryService
from src.services.verdict import VerdictService

logger = get_logger(__name__)


class FeedbackOrchestrator:
    def __init__(self):
        self.interview_pipeline = InterviewPipeline()
        self.feedback_pipeline = FeedbackPipeline()
        self.evidence_service = EvidenceService()
        self.judge_service = JudgeService()
        self.summary_service = SummaryService()
        self.verdict_service = VerdictService()

    async def process_complete(
        self,
        interview_transcript: str,
        feedback_transcript: str,
        topics: list[TopicInput],
        candidate_name: str | None = None,
        segments: list[dict] | None = None,
    ) -> CompleteProcessingResponse:
        has_interview = bool(interview_transcript and interview_transcript.strip())

        async with AnthropicClient() as client:
            if has_interview:
                interview_task = asyncio.create_task(
                    self.interview_pipeline.process(
                        interview_transcript, topics, candidate_name, client, segments
                    )
                )
            feedback_task = asyncio.create_task(
                self.feedback_pipeline.process(feedback_transcript, topics, client)
            )

            if has_interview:
                interview_result, feedback_result = await asyncio.gather(
                    interview_task, feedback_task
                )
            else:
                logger.info("no_interview_transcript_skipping_interview_pipeline")
                feedback_result = await feedback_task
                interview_result = {
                    "chunks_data": [],
                    "chunks_lookup": {},
                    "topics_lookup": {},
                    "mapping_result": {"topic_mappings": []},
                    "detection_info": {"auto_detected": False},
                    "candidate": "Unknown",
                    "interviewer": "Unknown",
                }

        chunk_map = {}
        for chunk in interview_result["chunks_data"]:
            chunk_map[str(chunk.id)] = ChunkContent(
                time_range=chunk.time_range,
                speaker=chunk.primary_speaker,
                content=chunk.content,
            )

        topic_map = {}
        for i, topic in enumerate(topics, 1):
            topic_id = f"T{i}"
            topic_map[topic_id] = TopicInfo(
                heading=topic.heading,
                description=topic.description,
            )
        topic_map["T_OVERALL"] = TopicInfo(
            heading="Overall",
            description="Holistic, candidate-level feedback not specific to any single topic",
        )

        topic_chunk_map = {}
        raw_mappings = interview_result["mapping_result"].get("topic_mappings", [])
        for mapping in raw_mappings:
            topic_id = mapping.get("topic_id")
            chunk_ids = mapping.get(
                "relevant_chunk_ids", mapping.get("relevant_chunks", [])
            )
            topic_chunk_map[topic_id] = [str(cid) for cid in chunk_ids]

        for topic_id in topic_map.keys():
            if topic_id not in topic_chunk_map:
                topic_chunk_map[topic_id] = []

        logger.info(
            "pipeline_interview_result",
            chunk_count=len(chunk_map),
            topic_mapping_count=len(raw_mappings),
            topic_chunk_summary={tid: len(cids) for tid, cids in topic_chunk_map.items()},
        )

        topic_feedback_map: dict[str, list[FeedbackItem]] = {}
        for topic_id in topic_map.keys():
            topic_feedback_map[topic_id] = []

        for topic_id, result in feedback_result["condensed_results"].items():
            feedback_items = []
            for item in result["condensed"]:
                feedback_items.append(
                    FeedbackItem(
                        feedback=item.get("feedback_bullet", ""),
                        antifeedback=item.get("antifeedback_bullet", ""),
                        sentiment=item.get("sentiment", "neutral"),
                        source_context=item.get("source_context", ""),
                        claim_strength=item.get("claim_strength", "primary"),
                    )
                )
            topic_feedback_map[topic_id] = feedback_items

        logger.info(
            "pipeline_feedback_result",
            condensed_topics=list(feedback_result["condensed_results"].keys()),
            feedback_counts={tid: len(items) for tid, items in topic_feedback_map.items() if items},
        )

        return CompleteProcessingResponse(
            chunk_map=chunk_map,
            topic_map=topic_map,
            topic_chunk_map=topic_chunk_map,
            topic_feedback_map=topic_feedback_map,
        )

    async def extract_evidence(
        self,
        chunk_map: dict[str, ChunkContent],
        topic_map: dict[str, TopicInfo],
        topic_chunk_map: dict[str, list[str]],
        topic_feedback_map: dict[str, list[FeedbackItem]],
        role_context: RoleContext | None = None,
    ) -> EvidenceExtractionResponse:
        enriched_feedback = await self.evidence_service.extract_all(
            chunk_map, topic_map, topic_chunk_map, topic_feedback_map, role_context
        )
        return EvidenceExtractionResponse(enriched_feedback=enriched_feedback)

    async def judge_feedback(
        self,
        enriched_feedback: list[EnrichedFeedbackItem],
        role_context: RoleContext | None = None,
    ) -> JudgeResponse:
        judged_feedback = await self.judge_service.judge_all(
            enriched_feedback, role_context
        )
        return JudgeResponse(
            judged_feedback=judged_feedback,
            role_context_used=role_context or RoleContext(),
        )

    async def generate_summaries(
        self,
        judged_feedback: list[JudgedFeedbackItem],
        holistic_notes: list[FeedbackItem] | None = None,
        verbal_verdict: str | None = None,
    ) -> SummaryResponse:
        result = await self.summary_service.generate_summaries(
            judged_feedback,
            holistic_notes=holistic_notes,
            verbal_verdict=verbal_verdict,
        )
        return SummaryResponse(
            question_summaries=result.question_summaries,
            round_summary=result.round_summary,
            competency_snapshots=result.competency_snapshots,
            round_rating=result.round_rating,
            overall_feedback=result.overall_feedback,
        )

    async def process_full_pipeline(
        self,
        interview_transcript: str,
        feedback_transcript: str,
        topics: list[TopicInput],
        candidate_name: str | None = None,
        role_context: RoleContext | None = None,
        segments: list[dict] | None = None,
    ) -> tuple[CompleteProcessingResponse, EvidenceExtractionResponse, JudgeResponse, SummaryResponse]:
        complete_task = asyncio.create_task(
            self.process_complete(
                interview_transcript, feedback_transcript, topics, candidate_name, segments
            )
        )
        verdict_task = asyncio.create_task(
            self.verdict_service.extract_verdict(feedback_transcript)
        )

        complete_result, verdict_result = await asyncio.gather(
            complete_task, verdict_task
        )

        logger.info(
            "pipeline_verdict",
            primary_rating=verdict_result.primary_rating,
        )

        # T_OVERALL bullets are the interviewer's holistic verdict reasoning
        # ("good fit for team", "trusted with ownership"). They are NOT
        # transcript-grounded claims, so we partition them out of the
        # evidence + judge path and flow them directly to the summary stage
        # as interpretive context. complete_result.topic_feedback_map is left
        # intact so the raw extraction artifact still records what was
        # extracted; only the routing changes here.
        topic_feedback_map_for_judging = {
            tid: items
            for tid, items in complete_result.topic_feedback_map.items()
            if tid != "T_OVERALL"
        }
        holistic_notes = complete_result.topic_feedback_map.get("T_OVERALL", [])

        logger.info(
            "pipeline_partition",
            holistic_note_count=len(holistic_notes),
            judging_topics=list(topic_feedback_map_for_judging.keys()),
        )

        evidence_result = await self.extract_evidence(
            complete_result.chunk_map,
            complete_result.topic_map,
            complete_result.topic_chunk_map,
            topic_feedback_map_for_judging,
            role_context,
        )

        logger.info(
            "pipeline_evidence",
            enriched_count=len(evidence_result.enriched_feedback),
        )

        judge_result = await self.judge_feedback(
            evidence_result.enriched_feedback, role_context
        )

        logger.info(
            "pipeline_judge",
            judged_count=len(judge_result.judged_feedback),
        )

        summary_result = await self.generate_summaries(
            judge_result.judged_feedback,
            holistic_notes=holistic_notes,
            verbal_verdict=verdict_result.primary_rating,
        )

        logger.info(
            "pipeline_summary",
            question_summaries_count=len(summary_result.question_summaries),
            round_summary_len=len(summary_result.round_summary),
            calculated_rating=summary_result.round_rating,
            verdict_rating=verdict_result.primary_rating,
            overall_feedback_count=len(summary_result.overall_feedback),
        )

        summary_result = SummaryResponse(
            question_summaries=summary_result.question_summaries,
            round_summary=summary_result.round_summary,
            competency_snapshots=summary_result.competency_snapshots,
            round_rating=verdict_result.primary_rating,
            overall_feedback=summary_result.overall_feedback,
        )

        return complete_result, evidence_result, judge_result, summary_result
