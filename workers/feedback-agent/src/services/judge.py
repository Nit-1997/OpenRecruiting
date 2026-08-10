import asyncio
import json

from src.clients.llm import LLMGatewayClient
from src.logging import get_logger
from src.models import EnrichedFeedbackItem, JudgedFeedbackItem, RoleContext
from src.parsers import parse_json_response
from src.prompts import format_prompt

logger = get_logger(__name__)


class JudgeService:
    async def judge_all(
        self,
        enriched_feedback: list[EnrichedFeedbackItem],
        role_context: RoleContext | None = None,
    ) -> list[JudgedFeedbackItem]:
        role_context = role_context or RoleContext()

        async with LLMGatewayClient() as client:
            coroutines = [
                self._judge_single_feedback(item, role_context, client)
                for item in enriched_feedback
            ]
            results = await asyncio.gather(*coroutines, return_exceptions=True)

        judged_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("judge_failed", error=str(result))
                continue
            judged_results.append(result)

        judged_results.sort(key=lambda x: x.topic_id)
        return judged_results

    def _build_evidence_json(self, item: EnrichedFeedbackItem) -> str:
        evidence_obj = {
            "feedback_evidence": item.feedback_evidence or [],
            "antifeedback_evidence": item.antifeedback_evidence or [],
            "reasoning": item.reasoning or "",
        }
        return json.dumps(evidence_obj, indent=2)

    async def _judge_single_feedback(
        self,
        item: EnrichedFeedbackItem,
        role_context: RoleContext,
        client: LLMGatewayClient,
    ) -> JudgedFeedbackItem:
        prompt = format_prompt(
            "judge",
            role_title=role_context.role_title.strip() or "Not specified",
            experience_range=role_context.experience_range.strip() or "Not specified",
            must_have_skills=(
                ", ".join(role_context.must_have_skills)
                if role_context.must_have_skills
                else "Not specified"
            ),
            good_to_have_skills=(
                ", ".join(role_context.good_to_have_skills)
                if role_context.good_to_have_skills
                else "Not specified"
            ),
            job_description=role_context.job_description.strip() or "Not provided",
            intake_notes=role_context.intake_notes.strip() or "Not provided",
            topic=item.topic_heading,
            feedback=item.feedback,
            antifeedback=item.antifeedback,
            source_context=getattr(item, "source_context", "") or "(no surrounding context captured)",
            evidence_json=self._build_evidence_json(item),
        )

        try:
            response = await client.call_sonnet(prompt)
            result = parse_json_response(response)
            choice = result.get("choice", "feedback").lower()
            reasoning = result.get("reasoning", "")
        except Exception:
            choice = "feedback"
            reasoning = "Judgment failed, defaulting to original feedback"

        if choice == "antifeedback":
            return JudgedFeedbackItem(
                topic_id=item.topic_id,
                topic_heading=item.topic_heading,
                feedback=item.feedback,
                sentiment=item.sentiment,
                evidence_status="contradicted",
                evidence=item.antifeedback_evidence,
                reasoning=reasoning,
                claim_strength=getattr(item, "claim_strength", "primary"),
            )
        else:
            return JudgedFeedbackItem(
                topic_id=item.topic_id,
                topic_heading=item.topic_heading,
                feedback=item.feedback,
                sentiment=item.sentiment,
                evidence_status="supported",
                evidence=item.feedback_evidence,
                reasoning=reasoning,
                claim_strength=getattr(item, "claim_strength", "primary"),
            )
