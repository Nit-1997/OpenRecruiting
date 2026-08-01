import json

from src.clients.anthropic import AnthropicClient
from src.logging import get_logger
from src.models import TopicInput
from src.parsers import parse_json_response
from src.prompts import format_prompt

logger = get_logger(__name__)


class FeedbackPipeline:
    async def process(
        self,
        transcript: str,
        topics: list[TopicInput],
        client: AnthropicClient | None = None,
    ) -> dict:
        topics_for_prompt = []
        topics_lookup = {}

        for i, topic in enumerate(topics, 1):
            topic_id = f"T{i}"
            topics_for_prompt.append({
                "topic_id": topic_id,
                "heading": topic.heading,
                "description": topic.description,
            })
            topics_lookup[topic_id] = topic

        overall_topic = TopicInput(
            heading="Overall",
            description="Holistic, candidate-level feedback not specific to any single topic",
        )
        topics_for_prompt.append({
            "topic_id": "T_OVERALL",
            "heading": overall_topic.heading,
            "description": overall_topic.description,
        })
        topics_lookup["T_OVERALL"] = overall_topic

        extract_prompt = format_prompt(
            "feedback_extract",
            transcript=transcript,
            topics_json=json.dumps(topics_for_prompt, indent=2),
        )

        if client:
            extract_response = await client.call_sonnet(extract_prompt)
        else:
            async with AnthropicClient() as c:
                extract_response = await c.call_sonnet(extract_prompt)

        extract_result = parse_json_response(extract_response)
        extracted_bullets = extract_result.get("extracted_bullets", {})

        # New schema: each entry is {"bullet": "...", "source_context": "..."}.
        # Old (pre-PR 3) schema: each entry is a plain string like "[+] ...".
        # Normalize both into list[dict] with bullet + source_context.
        normalized_bullets: dict[str, list[dict]] = {}
        for topic_id, items in (extracted_bullets or {}).items():
            normalized = []
            for it in items or []:
                if isinstance(it, dict):
                    normalized.append({
                        "bullet": it.get("bullet", ""),
                        "source_context": it.get("source_context", ""),
                        "claim_strength": it.get("claim_strength", "primary"),
                    })
                else:
                    normalized.append({
                        "bullet": str(it),
                        "source_context": "",
                        "claim_strength": "primary",
                    })
            normalized_bullets[topic_id] = normalized

        condensed_results = {}

        for topic_id, entries in normalized_bullets.items():
            if not entries:
                continue

            topic = topics_lookup.get(topic_id)
            if not topic:
                continue

            raw_bullet_strings = [b["bullet"] for b in entries]

            # Build the bullets_with_context block — each entry shows the raw
            # bullet text plus its source_context so condense can apply the
            # through-line rule when merging same-sub-skill bullets.
            bullets_with_context = "\n\n".join(
                f"- {entry['bullet']} [{entry['claim_strength']}]\n  context: {entry['source_context'] or '(no surrounding context captured)'}"
                for entry in entries
            )

            condense_prompt = format_prompt(
                "feedback_condense",
                topic_heading=topic.heading,
                topic_description=topic.description,
                bullets_with_context=bullets_with_context,
            )

            try:
                if client:
                    condense_response = await client.call_sonnet(condense_prompt)
                else:
                    async with AnthropicClient() as c:
                        condense_response = await c.call_sonnet(condense_prompt)

                condense_result = parse_json_response(condense_response)
                condensed_results[topic_id] = {
                    "raw_bullets": raw_bullet_strings,
                    "condensed": condense_result.get("condensed_feedback", []),
                }
            except Exception:
                condensed_results[topic_id] = {
                    "raw_bullets": raw_bullet_strings,
                    "condensed": [],
                }

        return {
            "topics_lookup": topics_lookup,
            "condensed_results": condensed_results,
            "extracted_bullets": extracted_bullets,
            "normalized_bullets": normalized_bullets,
        }
