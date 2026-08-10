import asyncio
import json

from fastapi import APIRouter, HTTPException

from src.clients.llm import LLMGatewayClient
from src.models import (
    ChunkData,
    ParticipantDetection,
    TopicInput,
    TopicMapping,
    TopicMappingRequest,
    TopicMappingResponse,
)
from src.parsers import parse_json_response
from src.prompts import format_prompt
from src.services import EmbeddingService, InterviewPipeline
from src.utils import format_timedelta, get_all_speakers, get_primary_speaker

router = APIRouter(tags=["topics"])


@router.post("/map-topics", response_model=TopicMappingResponse)
async def map_topics(request: TopicMappingRequest):
    pipeline = InterviewPipeline()

    try:
        result = await pipeline.process(
            request.transcript, request.topics, request.candidate_name
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")

    total_chunks = len(result["chunks_data"])
    warnings = []

    topic_mappings = []
    for mapping in result["mapping_result"].get("topic_mappings", []):
        topic_id = mapping.get("topic_id")
        topic = result["topics_lookup"].get(topic_id)
        if not topic:
            continue

        chunk_ids = mapping.get(
            "relevant_chunk_ids", mapping.get("relevant_chunks", [])
        )
        relevant_chunks = [
            result["chunks_lookup"][cid] for cid in chunk_ids if cid in result["chunks_lookup"]
        ]

        topic_mappings.append(
            TopicMapping(
                topic_id=topic_id,
                heading=topic.heading,
                description=topic.description,
                relevant_chunk_ids=chunk_ids,
                relevant_chunks=relevant_chunks,
                reasoning=mapping.get("reasoning", ""),
            )
        )

    total_duration = 0
    if result["chunks_data"]:
        last_chunk = result["chunks_data"][-1]
        time_range = last_chunk.time_range
        if " - " in time_range:
            end_time_str = time_range.split(" - ")[1]
            parts = end_time_str.split(":")
            if len(parts) == 2:
                total_duration = int(parts[0])
            elif len(parts) == 3:
                total_duration = int(parts[0]) * 60 + int(parts[1])

    return TopicMappingResponse(
        transcript_metadata={
            "duration_minutes": total_duration,
            "total_chunks": total_chunks,
        },
        participants=ParticipantDetection(
            candidate=result.get("candidate", "Unknown"),
            interviewer=result.get("interviewer", "Unknown"),
            auto_detected=result["detection_info"]["auto_detected"],
            confidence=result["detection_info"]["confidence"],
            reasoning=result["detection_info"]["reasoning"],
        ),
        chunks=result["chunks_data"],
        topic_mappings=topic_mappings,
        warnings=warnings,
    )
