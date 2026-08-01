from dataclasses import dataclass

from src.clients.anthropic import AnthropicClient
from src.logging import get_logger
from src.parsers import parse_json_response
from src.prompts import format_prompt

logger = get_logger(__name__)


@dataclass
class Verdict:
    interviewer: str
    rating: str | None
    verbatim_trigger: str
    notes: str


@dataclass
class VerdictResult:
    verdicts: list[Verdict]
    primary_rating: str


class VerdictService:
    async def extract_verdict(
        self,
        feedback_transcript: str,
        client: AnthropicClient | None = None,
    ) -> VerdictResult:
        """
        Extract interviewer verdicts from feedback transcript.

        Returns VerdictResult with all verdicts and a primary_rating
        (first non-null rating, or 'maybe' if none found).
        """
        prompt = format_prompt(
            "verdict_extraction",
            transcript=feedback_transcript,
        )

        try:
            if client:
                response = await client.call_haiku(prompt)
            else:
                async with AnthropicClient() as c:
                    response = await c.call_haiku(prompt)

            result = parse_json_response(response)
            verdicts_data = result.get("verdicts", [])
        except Exception as e:
            logger.error("verdict_extraction_failed", error=str(e))
            return VerdictResult(
                verdicts=[],
                primary_rating="maybe",
            )

        verdicts = []
        primary_rating = "maybe"

        for v in verdicts_data:
            rating = v.get("rating")
            if rating == "null" or rating is None:
                rating = None

            verdict = Verdict(
                interviewer=v.get("interviewer", "Unknown"),
                rating=rating,
                verbatim_trigger=v.get("verbatim_trigger", ""),
                notes=v.get("notes", ""),
            )
            verdicts.append(verdict)

            if primary_rating == "maybe" and rating is not None:
                primary_rating = rating

        return VerdictResult(
            verdicts=verdicts,
            primary_rating=primary_rating,
        )
