import json

from src.chunking import SemanticChunker
from src.clients.llm import LLMGatewayClient
from src.logging import get_logger
from src.models import ChunkData, TopicInput
from src.parsers import TranscriptParser, parse_json_response
from src.prompts import format_prompt
from src.services.embedding import EmbeddingService
from src.utils import (
    extract_speakers,
    extract_participant_data_for_identification,
    format_timedelta,
    get_all_speakers,
    get_primary_speaker,
)

logger = get_logger(__name__)


class InterviewPipeline:
    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.parser = TranscriptParser()
        self.chunker = SemanticChunker(embedding_service=self.embedding_service)

    async def process(
        self,
        transcript: str,
        topics: list[TopicInput],
        candidate_name: str | None = None,
        client: LLMGatewayClient | None = None,
        segments: list[dict] | None = None,
    ) -> dict:
        try:
            parse_result = self.parser.parse(transcript)
            chunks = self.chunker.chunk(parse_result.utterances)
        except Exception as e:
            raise ValueError(f"Failed to parse transcript: {e}")

        detection_info = {"auto_detected": False, "confidence": None, "reasoning": None}
        candidate = "Unknown"
        interviewer = "Unknown"

        if candidate_name:
            candidate, interviewer = extract_speakers(chunks, candidate_name)

        if candidate == "Unknown" or interviewer == "Unknown":
            try:
                participants = await self._detect_participants(
                    transcript, client, segments=segments
                )
                candidate = participants.get("candidate", "Unknown")
                interviewer = participants.get("interviewer", "Unknown")
                detection_info = {
                    "auto_detected": True,
                    "confidence": participants.get("confidence"),
                    "reasoning": participants.get("reasoning"),
                }
            except Exception:
                detection_info["auto_detected"] = True

        total_duration = 0
        if chunks and chunks[-1].end_time:
            total_duration = int(chunks[-1].end_time.total_seconds() / 60)

        chunks_data = []
        chunks_lookup = {}
        for i, chunk in enumerate(chunks, 1):
            chunk_data = ChunkData(
                id=i,
                time_range=f"{format_timedelta(chunk.start_time)} - {format_timedelta(chunk.end_time)}",
                primary_speaker=get_primary_speaker(chunk),
                speakers=get_all_speakers(chunk),
                token_count=chunk.token_count,
                content=chunk.text[:3000] if len(chunk.text) > 3000 else chunk.text,
            )
            chunks_data.append(chunk_data)
            chunks_lookup[i] = chunk_data

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

        prompt = format_prompt(
            "topic_mapping",
            candidate_name=candidate,
            interviewer_names=interviewer,
            duration_minutes=total_duration,
            total_chunks=len(chunks),
            topics_json=json.dumps(topics_for_prompt, indent=2),
            chunks_json=json.dumps([c.model_dump() for c in chunks_data], indent=2),
        )

        if client:
            llm_response = await client.call_sonnet(prompt)
        else:
            async with LLMGatewayClient() as c:
                llm_response = await c.call_sonnet(prompt)

        mapping_result = parse_json_response(llm_response)

        return {
            "chunks_data": chunks_data,
            "chunks_lookup": chunks_lookup,
            "topics_lookup": topics_lookup,
            "mapping_result": mapping_result,
            "detection_info": detection_info,
            "candidate": candidate,
            "interviewer": interviewer,
        }

    async def _detect_participants(
        self,
        transcript: str,
        client: LLMGatewayClient | None = None,
        segments: list[dict] | None = None,
    ) -> dict:
        if segments:
            participant_data = extract_participant_data_for_identification(segments)
            if participant_data:
                prompt = format_prompt(
                    "participant_detection",
                    participant_data=json.dumps(participant_data, indent=2),
                )

                if client:
                    response = await client.call_haiku(prompt)
                else:
                    async with LLMGatewayClient() as c:
                        response = await c.call_haiku(prompt)

                result = parse_json_response(response)
                return self._convert_detection_result(result)

        excerpt = transcript[:8000]
        first_sentences = excerpt.split("\n")[:10]
        prompt = format_prompt(
            "participant_detection",
            participant_data=f'[{{"name": "Unknown", "first_sentences": {json.dumps(first_sentences)}}}]',
        )

        if client:
            response = await client.call_haiku(prompt)
        else:
            async with LLMGatewayClient() as c:
                response = await c.call_haiku(prompt)

        result = parse_json_response(response)
        return self._convert_detection_result(result)

    def _convert_detection_result(self, result: dict) -> dict:
        """Convert new prompt output format to existing expected format."""
        participants = result.get("participants", [])

        candidate = "Unknown"
        interviewers = []
        candidate_confidence = "low"

        for p in participants:
            if p.get("role") == "candidate" and candidate == "Unknown":
                candidate = p.get("name", "Unknown")
                candidate_confidence = p.get("confidence", "low")
            elif p.get("role") == "interviewer":
                interviewers.append(p.get("name", "Unknown"))

        interviewer_names = ", ".join(interviewers) if interviewers else "Unknown"

        return {
            "candidate": candidate,
            "interviewer": interviewer_names,
            "confidence": candidate_confidence,
            "reasoning": result.get("analysis_summary", ""),
        }
