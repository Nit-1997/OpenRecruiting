import asyncio

from src.clients.llm import LLMGatewayClient
from src.logging import get_logger
from src.models import FeedbackItem, JudgedFeedbackItem, QuestionSummary, SummaryResult
from src.parsers import parse_json_response
from src.prompts import format_prompt

logger = get_logger(__name__)


class SummaryService:
    async def generate_summaries(
        self,
        judged_feedback: list[JudgedFeedbackItem],
        holistic_notes: list[FeedbackItem] | None = None,
        verbal_verdict: str | None = None,
    ) -> SummaryResult:
        question_items = [
            item for item in judged_feedback if item.topic_id != "T_OVERALL"
        ]

        async with LLMGatewayClient() as client:
            coroutines = [
                self._generate_question_summary(item, client, verbal_verdict=verbal_verdict)
                for item in question_items
            ]
            results = await asyncio.gather(*coroutines, return_exceptions=True)

        question_summaries = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("summary_generation_failed", error=str(result))
                continue
            question_summaries.append(result)

        question_summaries.sort(key=lambda x: x.topic_id)

        holistic_notes = holistic_notes or []

        async with LLMGatewayClient() as client:
            round_summary, competency_snapshots = await self._generate_round_summary(
                question_summaries,
                judged_feedback,
                holistic_notes,
                verbal_verdict,
                client,
            )

        round_rating = self._calculate_rating(judged_feedback)
        # NOTE: evidence_status = "holistic" is a new third state alongside
        # "supported" / "contradicted". UI consumers (openrecruiting-admin scorecard)
        # currently coerce unknown statuses to "Not Supported" — when
        # overall_feedback rendering is added downstream, that consumer must
        # treat "holistic" as a distinct state (no badge, or "Overall" badge)
        # rather than running it through the supported/contradicted lens.
        overall_feedback_dicts = [
            {
                "feedback_data": item.feedback,
                "evidence": [],
                "evidence_status": "holistic",
            }
            for item in holistic_notes
        ]

        return SummaryResult(
            question_summaries=question_summaries,
            round_summary=round_summary,
            competency_snapshots=competency_snapshots,
            round_rating=round_rating,
            overall_feedback=overall_feedback_dicts,
        )

    async def _generate_question_summary(
        self,
        item: JudgedFeedbackItem,
        client: LLMGatewayClient,
        verbal_verdict: str | None = None,
    ) -> QuestionSummary:
        evidence_text = "\n".join(f"- {e}" for e in item.evidence) if item.evidence else "No specific evidence found"

        prompt = format_prompt(
            "question_summary",
            topic_heading=item.topic_heading,
            feedback=item.feedback,
            evidence=evidence_text,
            evidence_status=item.evidence_status,
            verbal_verdict=verbal_verdict or "unknown",
            claim_strength=getattr(item, "claim_strength", "primary"),
        )

        # Default to claim-polarity sentiment; the prompt now emits a
        # `finding_sentiment` that reflects the polarity of the actual
        # finding (after the contradicted-flip), which is what the
        # scorecard badge should track.
        finding_sentiment = item.sentiment
        try:
            response = await client.call_sonnet(prompt)
            result = parse_json_response(response)
            summary = result.get("summary", item.feedback)
            model_sentiment = result.get("finding_sentiment")
            if model_sentiment in ("positive", "negative", "neutral"):
                finding_sentiment = model_sentiment
        except Exception as e:
            logger.error("question_summary_llm_failed", error=str(e), topic_id=item.topic_id)
            summary = item.feedback

        return QuestionSummary(
            topic_id=item.topic_id,
            topic_heading=item.topic_heading,
            summary=summary,
            evidence_status=item.evidence_status,
            sentiment=finding_sentiment,
        )

    async def _generate_round_summary(
        self,
        question_summaries: list[QuestionSummary],
        judged_feedback: list[JudgedFeedbackItem],
        holistic_notes: list[FeedbackItem],
        verbal_verdict: str | None,
        client: LLMGatewayClient,
    ) -> tuple[str, str]:
        if not question_summaries:
            return "", ""

        # Build the holistic notes block from T_OVERALL items
        if holistic_notes:
            holistic_block = "\n".join(f"- {n.feedback}" for n in holistic_notes)
        else:
            holistic_block = "(none provided)"

        # Build the judged items reference block — pass evidence_status + reasoning
        # so the prompt can apply Rule 1 (contradicted = calibration, not failure)
        # with the actual transcript-grounded reasoning visible.
        judged_lines = []
        for item in judged_feedback:
            if item.topic_id == "T_OVERALL":
                # Defensive — T_OVERALL should already be partitioned out by
                # orchestrator (see Task 1.9), but skip if any slipped through.
                continue
            judged_lines.append(
                f"- [{item.topic_heading}] [{item.evidence_status}] [strength={getattr(item, 'claim_strength', 'primary')}] {item.feedback}\n"
                f"  reasoning: {item.reasoning}"
            )
        judged_block = "\n".join(judged_lines) if judged_lines else "(no judged items)"

        summaries_text = "\n".join(
            f"- {qs.topic_heading}: {qs.summary}" for qs in question_summaries
        )

        prompt = format_prompt(
            "round_summary",
            question_summaries=summaries_text,
            verbal_verdict=verbal_verdict or "unknown",
            interviewer_holistic_notes=holistic_block,
            judged_items=judged_block,
        )

        try:
            response = await client.call_sonnet(prompt)
            result = parse_json_response(response)
            overall = result.get("overall", "")
            competency_snapshots = result.get("competency_snapshots", "")
            return overall, competency_snapshots
        except Exception as e:
            logger.error("round_summary_llm_failed", error=str(e))
            return "Unable to generate summary", ""

    def _calculate_rating(self, judged_feedback: list[JudgedFeedbackItem]) -> str:
        question_items = [
            item for item in judged_feedback if item.topic_id != "T_OVERALL"
        ]

        if not question_items:
            return "maybe"

        positive_count = 0
        negative_count = 0
        supported_positive = 0
        supported_negative = 0

        for item in question_items:
            sentiment = item.sentiment.lower()
            is_supported = item.evidence_status == "supported"

            if sentiment == "positive":
                positive_count += 1
                if is_supported:
                    supported_positive += 1
            elif sentiment == "negative":
                negative_count += 1
                if is_supported:
                    supported_negative += 1

        total = len(question_items)

        strong_positive_ratio = supported_positive / total if total > 0 else 0
        strong_negative_ratio = supported_negative / total if total > 0 else 0

        if strong_positive_ratio >= 0.6 and supported_negative == 0:
            return "strong_yes"
        elif strong_negative_ratio >= 0.4 or supported_negative >= 2:
            return "no"
        elif strong_positive_ratio >= 0.4:
            return "yes"
        elif strong_negative_ratio >= 0.2 or supported_negative >= 1:
            return "maybe"
        else:
            return "maybe"
