import asyncio

from src.clients.llm import LLMGatewayClient
from src.logging import get_logger
from src.models import ChunkContent, EnrichedFeedbackItem, FeedbackItem, RoleContext, TopicInfo
from src.parsers import parse_json_response
from src.prompts import format_prompt

logger = get_logger(__name__)


class EvidenceService:
    async def extract_all(
        self,
        chunk_map: dict[str, ChunkContent],
        topic_map: dict[str, TopicInfo],
        topic_chunk_map: dict[str, list[str]],
        topic_feedback_map: dict[str, list[FeedbackItem]],
        role_context: RoleContext | None = None,
    ) -> list[EnrichedFeedbackItem]:
        tasks = []
        no_evidence_items = []
        ctx = role_context or RoleContext()

        for topic_id, feedback_items in topic_feedback_map.items():
            if not feedback_items:
                continue

            topic_info = topic_map.get(topic_id)
            if not topic_info:
                continue

            chunk_ids = topic_chunk_map.get(topic_id, [])
            chunks_text = self._format_chunks_for_evidence(chunk_ids, chunk_map) if chunk_ids else ""

            if not chunks_text:
                logger.info(
                    "no_chunks_for_topic",
                    topic_id=topic_id,
                    feedback_count=len(feedback_items),
                )
                for feedback_item in feedback_items:
                    no_evidence_items.append(EnrichedFeedbackItem(
                        topic_id=topic_id,
                        topic_heading=topic_info.heading,
                        feedback=feedback_item.feedback,
                        antifeedback=feedback_item.antifeedback,
                        sentiment=feedback_item.sentiment,
                        feedback_evidence=[],
                        antifeedback_evidence=[],
                        reasoning="No interview chunks available for evidence extraction",
                        source_context=getattr(feedback_item, "source_context", "") or "",
                    ))
                continue

            for feedback_item in feedback_items:
                tasks.append({
                    "topic_id": topic_id,
                    "topic_heading": topic_info.heading,
                    "topic_description": topic_info.description,
                    "feedback": feedback_item.feedback,
                    "antifeedback": feedback_item.antifeedback,
                    "sentiment": feedback_item.sentiment,
                    "source_context": getattr(feedback_item, "source_context", "") or "",
                    "chunks_text": chunks_text,
                    "role_context": ctx,
                })

        if tasks:
            async with LLMGatewayClient() as client:
                coroutines = [
                    self._extract_single_evidence(
                        task["topic_id"],
                        task["topic_heading"],
                        task["topic_description"],
                        task["feedback"],
                        task["antifeedback"],
                        task["sentiment"],
                        task["source_context"],
                        task["chunks_text"],
                        task["role_context"],
                        client,
                    )
                    for task in tasks
                ]
                results = await asyncio.gather(*coroutines, return_exceptions=True)
        else:
            results = []

        enriched_results = list(no_evidence_items)
        for result in results:
            if isinstance(result, Exception):
                logger.error("evidence_extraction_failed", error=str(result))
                continue
            enriched_results.append(result)

        enriched_results.sort(key=lambda x: x.topic_id)

        logger.info(
            "evidence_extraction_complete",
            total_items=len(enriched_results),
            with_evidence=len(tasks),
            without_evidence=len(no_evidence_items),
        )

        return enriched_results

    def _format_chunks_for_evidence(
        self, chunk_ids: list[str], chunk_map: dict[str, ChunkContent]
    ) -> str:
        # Format chunks as "speaker (time_range): content" with NO chunk ID.
        # Internal chunk IDs were previously prefixed as "[Chunk N]" but the
        # LLM occasionally echoed those labels into user-facing evidence
        # bullets (e.g. "In Chunk 27, the candidate ..."). Removing the
        # internal label at the source eliminates the leakage class entirely.
        chunks_text = []
        for cid in chunk_ids:
            chunk = chunk_map.get(cid)
            if chunk:
                chunks_text.append(
                    f"{chunk.speaker} ({chunk.time_range}):\n{chunk.content}\n"
                )
        return "\n---\n".join(chunks_text)

    async def _extract_single_evidence(
        self,
        topic_id: str,
        topic_heading: str,
        topic_description: str,
        feedback: str,
        antifeedback: str,
        sentiment: str,
        source_context: str,
        chunks_text: str,
        role_context: RoleContext,
        client: LLMGatewayClient,
    ) -> EnrichedFeedbackItem:
        prompt = format_prompt(
            "evidence_extraction",
            feedback=feedback,
            antifeedback=antifeedback,
            topic_heading=topic_heading,
            topic_description=topic_description,
            source_context=source_context or "(no surrounding context captured)",
            chunks_text=chunks_text,
            role_title=role_context.role_title,
            experience_range=role_context.experience_range,
            must_have_skills=", ".join(role_context.must_have_skills) if role_context.must_have_skills else "Not specified",
            good_to_have_skills=", ".join(role_context.good_to_have_skills) if role_context.good_to_have_skills else "Not specified",
            intake_notes=role_context.intake_notes or "Not provided",
        )

        try:
            response = await client.call_sonnet(prompt)
            result = parse_json_response(response)
        except Exception:
            result = {
                "feedback_evidence": [],
                "antifeedback_evidence": [],
                "reasoning": "Evidence extraction failed",
            }

        return EnrichedFeedbackItem(
            topic_id=topic_id,
            topic_heading=topic_heading,
            feedback=feedback,
            antifeedback=antifeedback,
            sentiment=sentiment,
            feedback_evidence=result.get("feedback_evidence", []),
            antifeedback_evidence=result.get("antifeedback_evidence", []),
            reasoning=result.get("reasoning", ""),
            source_context=source_context,
        )
