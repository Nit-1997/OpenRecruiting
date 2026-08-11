import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

import requests

from src.config import get_settings
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.chunking import SemanticChunker
from src.parsers import TranscriptParser
from src.prompts import (
    PARTICIPANT_DETECTION_PROMPT,
    TOPIC_MAPPING_PROMPT,
    FEEDBACK_EXTRACT_PROMPT,
    FEEDBACK_CONDENSE_PROMPT,
    EVIDENCE_EXTRACTION_PROMPT,
    JUDGE_PROMPT,
)
from src.services import EmbeddingService


app = FastAPI(title="Interview Topic Mapper API")

embedding_service = EmbeddingService()
parser = TranscriptParser()
chunker = SemanticChunker(embedding_service=embedding_service)


class Topic(BaseModel):
    heading: str
    description: str


class TopicMappingRequest(BaseModel):
    transcript: str
    candidate_name: str | None = None
    topics: list[Topic]


class ChunkData(BaseModel):
    id: int
    time_range: str
    primary_speaker: str
    speakers: list[str]
    token_count: int
    content: str


class TopicMapping(BaseModel):
    topic_id: str
    heading: str
    description: str
    relevant_chunk_ids: list[int]
    relevant_chunks: list[ChunkData]
    reasoning: str


class ParticipantDetection(BaseModel):
    candidate: str
    interviewer: str
    auto_detected: bool
    confidence: str | None = None
    reasoning: str | None = None


class TopicMappingResponse(BaseModel):
    transcript_metadata: dict
    participants: ParticipantDetection
    chunks: list[ChunkData]
    topic_mappings: list[TopicMapping]
    warnings: list[str] = []


class FeedbackProcessingRequest(BaseModel):
    transcript: str
    topics: list[Topic]


class FeedbackBullet(BaseModel):
    feedback_bullet: str
    antifeedback_bullet: str
    sentiment: str = "neutral"


class TopicFeedbackResult(BaseModel):
    topic_id: str
    heading: str
    description: str
    raw_bullets: list[str]
    condensed_feedback: list[FeedbackBullet]


class FeedbackProcessingResponse(BaseModel):
    topic_feedback: list[TopicFeedbackResult]
    debug_extracted_bullets: dict[str, list[str]] | None = None


class CompleteProcessingRequest(BaseModel):
    interview_transcript: str
    feedback_transcript: str
    topics: list[Topic]
    candidate_name: str | None = None


class ChunkContent(BaseModel):
    time_range: str
    speaker: str
    content: str


class TopicInfo(BaseModel):
    heading: str
    description: str


class FeedbackItem(BaseModel):
    feedback: str
    antifeedback: str
    sentiment: str
    source_context: str = ""


class CompleteProcessingResponse(BaseModel):
    chunk_map: dict[str, ChunkContent]
    topic_map: dict[str, TopicInfo]
    topic_chunk_map: dict[str, list[str]]
    topic_feedback_map: dict[str, list[FeedbackItem]]


class EnrichedFeedbackItem(BaseModel):
    topic_id: str
    topic_heading: str
    feedback: str
    antifeedback: str
    sentiment: str
    feedback_evidence: list[str]
    antifeedback_evidence: list[str]
    reasoning: str


class EvidenceExtractionRequest(BaseModel):
    chunk_map: dict[str, ChunkContent]
    topic_map: dict[str, TopicInfo]
    topic_chunk_map: dict[str, list[str]]
    topic_feedback_map: dict[str, list[FeedbackItem]]
    role_context: RoleContext | None = None


class EvidenceExtractionResponse(BaseModel):
    enriched_feedback: list[EnrichedFeedbackItem]


class RoleContext(BaseModel):
    role_title: str = "Product Manager"
    experience_range: str = "3-6 years"
    must_have_skills: list[str] = []
    good_to_have_skills: list[str] = []
    job_description: str = ""
    intake_notes: str = ""


class JudgedFeedbackItem(BaseModel):
    topic_id: str
    topic_heading: str
    feedback: str
    sentiment: str
    evidence_status: str
    evidence: list[str]
    reasoning: str


class JudgeRequest(BaseModel):
    enriched_feedback: list[EnrichedFeedbackItem]
    role_context: RoleContext | None = None


class JudgeResponse(BaseModel):
    judged_feedback: list[JudgedFeedbackItem]
    role_context_used: RoleContext | None = None


def format_timedelta(td: timedelta | None) -> str:
    if td is None:
        return "N/A"
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def extract_speakers_from_text(text: str) -> list[str]:
    import re
    pattern = r'\[\d+:\d+\]\s*([^:]+):'
    matches = re.findall(pattern, text)
    speakers = []
    for match in matches:
        speaker = match.strip()
        if speaker and speaker not in speakers:
            speakers.append(speaker)
    return speakers


def get_primary_speaker(chunk) -> str:
    speaker_counts = {}
    for utterance in chunk.utterances:
        speaker = utterance.speaker or "Unknown"
        if speaker != "Unknown":
            speaker_counts[speaker] = speaker_counts.get(speaker, 0) + len(utterance.text)

    if speaker_counts:
        return max(speaker_counts, key=speaker_counts.get)

    speakers = extract_speakers_from_text(chunk.text)
    if speakers:
        text_counts = {}
        for speaker in speakers:
            text_counts[speaker] = chunk.text.count(f"] {speaker}:")
        if text_counts:
            return max(text_counts, key=text_counts.get)

    return "Unknown"


def get_all_speakers(chunk) -> list[str]:
    speakers = []
    for utterance in chunk.utterances:
        if utterance.speaker and utterance.speaker not in speakers:
            speakers.append(utterance.speaker)

    if not speakers or speakers == ["Unknown"]:
        speakers = extract_speakers_from_text(chunk.text)

    return speakers if speakers else ["Unknown"]


def extract_speakers(chunks, candidate_name: str) -> tuple[str, str]:
    all_speakers = set()
    for chunk in chunks:
        for utterance in chunk.utterances:
            if utterance.speaker:
                all_speakers.add(utterance.speaker)

    speakers = list(all_speakers)
    candidate = "Unknown"
    interviewer = "Unknown"

    for speaker in speakers:
        if candidate_name.lower() in speaker.lower():
            candidate = speaker
            break

    for speaker in speakers:
        if speaker != candidate:
            interviewer = speaker
            break

    return candidate, interviewer


def call_sonnet(prompt: str) -> str:
    """Blocking gateway call for this module's nine topic-mapping routes.

    A SECOND egress path, separate from src/clients/llm.py, which the spec's
    per-service table never mentioned — it hardcoded claude-sonnet-4-6 and read
    the provider credential directly. It is kept rather than deleted: nothing in either
    Dockerfile runs this module (the compose image runs app:app, the Lambda runs
    production.handler.handler), but src/ui/topic_mapper.py documents
    `uvicorn src.api.server:app` as a developer entry point, so it is a working
    tool. Migrating it costs nothing and removes the last provider egress from
    this worker; deleting a dev tool is a separate decision for its owner.
    """
    settings = get_settings()
    if not settings.litellm_master_key:
        raise ValueError("LITELLM_MASTER_KEY not set")

    headers = {
        "authorization": f"Bearer {settings.litellm_master_key}",
        "content-type": "application/json",
    }
    payload = {
        "model": settings.llm_model_sonnet,
        "max_tokens": 4096,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = requests.post(
        f"{settings.llm_gateway_url}/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"].get("content") or ""


def parse_json_response(response: str) -> dict:
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
    return json.loads(response.strip())


def detect_participants(transcript: str) -> dict:
    excerpt = transcript[:8000]
    first_sentences = excerpt.split("\n")[:10]

    prompt = PARTICIPANT_DETECTION_PROMPT.format(
        participant_data=json.dumps([{"name": "Unknown", "first_sentences": first_sentences}], indent=2)
    )

    response = call_sonnet(prompt)
    result = parse_json_response(response)

    participants = result.get("participants", [])
    candidate = "Unknown"
    interviewer = "Unknown"

    for p in participants:
        if p.get("role") == "candidate" and candidate == "Unknown":
            candidate = p.get("name", "Unknown")
        elif p.get("role") == "interviewer" and interviewer == "Unknown":
            interviewer = p.get("name", "Unknown")

    return {
        "candidate": candidate,
        "interviewer": interviewer,
        "confidence": result.get("participants", [{}])[0].get("confidence", "low") if participants else "low",
        "reasoning": result.get("analysis_summary", ""),
    }


@app.post("/map-topics", response_model=TopicMappingResponse)
def map_topics(request: TopicMappingRequest):
    try:
        parse_result = parser.parse(request.transcript)
        chunks = chunker.chunk(parse_result.utterances)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse transcript: {e}")

    detection_info = {"auto_detected": False, "confidence": None, "reasoning": None}

    candidate = "Unknown"
    interviewer = "Unknown"

    if request.candidate_name:
        candidate, interviewer = extract_speakers(chunks, request.candidate_name)

    if candidate == "Unknown" or interviewer == "Unknown":
        try:
            participants = detect_participants(request.transcript)
            candidate = participants.get("candidate", "Unknown")
            interviewer = participants.get("interviewer", "Unknown")
            detection_info = {
                "auto_detected": True,
                "confidence": participants.get("confidence"),
                "reasoning": participants.get("reasoning"),
            }
        except Exception as e:
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
    for i, topic in enumerate(request.topics, 1):
        topic_id = f"T{i}"
        topics_for_prompt.append({
            "topic_id": topic_id,
            "heading": topic.heading,
            "description": topic.description,
        })
        topics_lookup[topic_id] = topic

    prompt = TOPIC_MAPPING_PROMPT.format(
        candidate_name=candidate,
        interviewer_names=interviewer,
        duration_minutes=total_duration,
        total_chunks=len(chunks),
        topics_json=json.dumps(topics_for_prompt, indent=2),
        chunks_json=json.dumps([c.model_dump() for c in chunks_data], indent=2),
    )

    try:
        llm_response = call_sonnet(prompt)
        mapping_result = parse_json_response(llm_response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM mapping failed: {e}")

    topic_mappings = []
    warnings = []
    total_chunks = len(chunks)

    for mapping in mapping_result.get("topic_mappings", []):
        topic_id = mapping.get("topic_id")
        topic = topics_lookup.get(topic_id)
        if not topic:
            continue

        chunk_ids = mapping.get("relevant_chunk_ids", mapping.get("relevant_chunks", []))
        relevant_chunks = [chunks_lookup[cid] for cid in chunk_ids if cid in chunks_lookup]

        topic_mappings.append(TopicMapping(
            topic_id=topic_id,
            heading=topic.heading,
            description=topic.description,
            relevant_chunk_ids=chunk_ids,
            relevant_chunks=relevant_chunks,
            reasoning=mapping.get("reasoning", ""),
        ))

    return TopicMappingResponse(
        transcript_metadata={
            "duration_minutes": total_duration,
            "total_chunks": len(chunks),
        },
        participants=ParticipantDetection(
            candidate=candidate,
            interviewer=interviewer,
            auto_detected=detection_info["auto_detected"],
            confidence=detection_info["confidence"],
            reasoning=detection_info["reasoning"],
        ),
        chunks=chunks_data,
        topic_mappings=topic_mappings,
        warnings=warnings,
    )


@app.post("/process-feedback", response_model=FeedbackProcessingResponse)
def process_feedback(request: FeedbackProcessingRequest):
    topics_for_prompt = []
    topics_lookup = {}

    for i, topic in enumerate(request.topics, 1):
        topic_id = f"T{i}"
        topics_for_prompt.append({
            "topic_id": topic_id,
            "heading": topic.heading,
            "description": topic.description,
        })
        topics_lookup[topic_id] = topic

    overall_topic = Topic(
        heading="Overall",
        description="Holistic, candidate-level feedback not specific to any single topic",
    )
    topics_for_prompt.append({
        "topic_id": "T_OVERALL",
        "heading": overall_topic.heading,
        "description": overall_topic.description,
    })
    topics_lookup["T_OVERALL"] = overall_topic

    extract_prompt = FEEDBACK_EXTRACT_PROMPT.format(
        transcript=request.transcript,
        topics_json=json.dumps(topics_for_prompt, indent=2),
    )

    try:
        extract_response = call_sonnet(extract_prompt)
        extract_result = parse_json_response(extract_response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feedback extraction failed: {e}")

    extracted_bullets = extract_result.get("extracted_bullets", {})

    topic_feedback_results = []

    for topic_id, bullets in extracted_bullets.items():
        if not bullets:
            continue

        topic = topics_lookup.get(topic_id)
        if not topic:
            continue

        condense_prompt = FEEDBACK_CONDENSE_PROMPT.format(
            topic_heading=topic.heading,
            topic_description=topic.description,
            bullets_json=json.dumps(bullets, indent=2),
        )

        try:
            condense_response = call_sonnet(condense_prompt)
            condense_result = parse_json_response(condense_response)
        except Exception as e:
            condense_result = {"condensed_feedback": []}

        condensed_items = []
        for item in condense_result.get("condensed_feedback", []):
            condensed_items.append(FeedbackBullet(
                feedback_bullet=item.get("feedback_bullet", ""),
                antifeedback_bullet=item.get("antifeedback_bullet", ""),
                sentiment=item.get("sentiment", "neutral"),
            ))

        topic_feedback_results.append(TopicFeedbackResult(
            topic_id=topic_id,
            heading=topic.heading,
            description=topic.description,
            raw_bullets=bullets,
            condensed_feedback=condensed_items,
        ))

    return FeedbackProcessingResponse(
        topic_feedback=topic_feedback_results,
        debug_extracted_bullets=extracted_bullets,
    )


def _run_interview_pipeline(transcript: str, topics: list[Topic], candidate_name: str | None) -> dict:
    try:
        parse_result = parser.parse(transcript)
        chunks = chunker.chunk(parse_result.utterances)
    except Exception as e:
        raise ValueError(f"Failed to parse transcript: {e}")

    detection_info = {"auto_detected": False, "confidence": None, "reasoning": None}
    candidate = "Unknown"
    interviewer = "Unknown"

    if candidate_name:
        candidate, interviewer = extract_speakers(chunks, candidate_name)

    if candidate == "Unknown" or interviewer == "Unknown":
        try:
            participants = detect_participants(transcript)
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

    prompt = TOPIC_MAPPING_PROMPT.format(
        candidate_name=candidate,
        interviewer_names=interviewer,
        duration_minutes=total_duration,
        total_chunks=len(chunks),
        topics_json=json.dumps(topics_for_prompt, indent=2),
        chunks_json=json.dumps([c.model_dump() for c in chunks_data], indent=2),
    )

    llm_response = call_sonnet(prompt)
    mapping_result = parse_json_response(llm_response)

    return {
        "chunks_data": chunks_data,
        "chunks_lookup": chunks_lookup,
        "topics_lookup": topics_lookup,
        "mapping_result": mapping_result,
    }


def _run_feedback_pipeline(transcript: str, topics: list[Topic]) -> dict:
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

    overall_topic = Topic(
        heading="Overall",
        description="Holistic, candidate-level feedback not specific to any single topic",
    )
    topics_for_prompt.append({
        "topic_id": "T_OVERALL",
        "heading": overall_topic.heading,
        "description": overall_topic.description,
    })
    topics_lookup["T_OVERALL"] = overall_topic

    extract_prompt = FEEDBACK_EXTRACT_PROMPT.format(
        transcript=transcript,
        topics_json=json.dumps(topics_for_prompt, indent=2),
    )

    extract_response = call_sonnet(extract_prompt)
    extract_result = parse_json_response(extract_response)
    extracted_bullets = extract_result.get("extracted_bullets", {})

    condensed_results = {}

    for topic_id, bullets in extracted_bullets.items():
        if not bullets:
            continue

        topic = topics_lookup.get(topic_id)
        if not topic:
            continue

        condense_prompt = FEEDBACK_CONDENSE_PROMPT.format(
            topic_heading=topic.heading,
            topic_description=topic.description,
            bullets_json=json.dumps(bullets, indent=2),
        )

        try:
            condense_response = call_sonnet(condense_prompt)
            condense_result = parse_json_response(condense_response)
            condensed_results[topic_id] = {
                "raw_bullets": bullets,
                "condensed": condense_result.get("condensed_feedback", []),
            }
        except Exception:
            condensed_results[topic_id] = {
                "raw_bullets": bullets,
                "condensed": [],
            }

    return {
        "topics_lookup": topics_lookup,
        "condensed_results": condensed_results,
    }


@app.post("/process-complete", response_model=CompleteProcessingResponse)
def process_complete(request: CompleteProcessingRequest):
    interview_result = None
    feedback_result = None
    interview_error = None
    feedback_error = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        interview_future = executor.submit(
            _run_interview_pipeline,
            request.interview_transcript,
            request.topics,
            request.candidate_name,
        )
        feedback_future = executor.submit(
            _run_feedback_pipeline,
            request.feedback_transcript,
            request.topics,
        )

        for future in as_completed([interview_future, feedback_future]):
            if future == interview_future:
                try:
                    interview_result = future.result()
                except Exception as e:
                    interview_error = str(e)
            else:
                try:
                    feedback_result = future.result()
                except Exception as e:
                    feedback_error = str(e)

    if interview_error:
        raise HTTPException(status_code=500, detail=f"Interview pipeline failed: {interview_error}")
    if feedback_error:
        raise HTTPException(status_code=500, detail=f"Feedback pipeline failed: {feedback_error}")

    chunk_map = {}
    for chunk in interview_result["chunks_data"]:
        chunk_map[str(chunk.id)] = ChunkContent(
            time_range=chunk.time_range,
            speaker=chunk.primary_speaker,
            content=chunk.content,
        )

    topic_map = {}
    for i, topic in enumerate(request.topics, 1):
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
    for mapping in interview_result["mapping_result"].get("topic_mappings", []):
        topic_id = mapping.get("topic_id")
        chunk_ids = mapping.get("relevant_chunk_ids", mapping.get("relevant_chunks", []))
        topic_chunk_map[topic_id] = [str(cid) for cid in chunk_ids]

    for topic_id in topic_map.keys():
        if topic_id not in topic_chunk_map:
            topic_chunk_map[topic_id] = []

    topic_feedback_map = {}
    for topic_id in topic_map.keys():
        topic_feedback_map[topic_id] = []

    for topic_id, result in feedback_result["condensed_results"].items():
        feedback_items = []
        for item in result["condensed"]:
            feedback_items.append(FeedbackItem(
                feedback=item.get("feedback_bullet", ""),
                antifeedback=item.get("antifeedback_bullet", ""),
                sentiment=item.get("sentiment", "neutral"),
                source_context=item.get("source_context", ""),
            ))
        topic_feedback_map[topic_id] = feedback_items

    return CompleteProcessingResponse(
        chunk_map=chunk_map,
        topic_map=topic_map,
        topic_chunk_map=topic_chunk_map,
        topic_feedback_map=topic_feedback_map,
    )


def _extract_single_evidence(
    topic_id: str,
    topic_heading: str,
    topic_description: str,
    feedback: str,
    antifeedback: str,
    sentiment: str,
    chunks_text: str,
    role_context: RoleContext,
) -> EnrichedFeedbackItem:
    prompt = EVIDENCE_EXTRACTION_PROMPT.format(
        feedback=feedback,
        antifeedback=antifeedback,
        topic_heading=topic_heading,
        topic_description=topic_description,
        chunks_text=chunks_text,
        role_title=role_context.role_title,
        experience_range=role_context.experience_range,
        must_have_skills=", ".join(role_context.must_have_skills) if role_context.must_have_skills else "Not specified",
        good_to_have_skills=", ".join(role_context.good_to_have_skills) if role_context.good_to_have_skills else "Not specified",
        intake_notes=role_context.intake_notes or "Not provided",
    )

    try:
        response = call_sonnet(prompt)
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
    )


def _format_chunks_for_evidence(chunk_ids: list[str], chunk_map: dict[str, ChunkContent]) -> str:
    chunks_text = []
    for cid in chunk_ids:
        chunk = chunk_map.get(cid)
        if chunk:
            chunks_text.append(
                f"[Chunk {cid}] ({chunk.time_range}) {chunk.speaker}:\n{chunk.content}\n"
            )
    return "\n---\n".join(chunks_text)


@app.post("/extract-evidence", response_model=EvidenceExtractionResponse)
def extract_evidence(request: EvidenceExtractionRequest):
    tasks = []
    role_ctx = request.role_context or RoleContext()

    for topic_id, feedback_items in request.topic_feedback_map.items():
        if not feedback_items:
            continue

        chunk_ids = request.topic_chunk_map.get(topic_id, [])
        if not chunk_ids:
            continue

        chunks_text = _format_chunks_for_evidence(chunk_ids, request.chunk_map)
        topic_info = request.topic_map.get(topic_id)
        if not topic_info:
            continue

        for feedback_item in feedback_items:
            tasks.append({
                "topic_id": topic_id,
                "topic_heading": topic_info.heading,
                "topic_description": topic_info.description,
                "feedback": feedback_item.feedback,
                "antifeedback": feedback_item.antifeedback,
                "sentiment": feedback_item.sentiment,
                "chunks_text": chunks_text,
                "role_context": role_ctx,
            })

    enriched_results = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(
                _extract_single_evidence,
                task["topic_id"],
                task["topic_heading"],
                task["topic_description"],
                task["feedback"],
                task["antifeedback"],
                task["sentiment"],
                task["chunks_text"],
                task["role_context"],
            )
            for task in tasks
        ]

        for future in as_completed(futures):
            try:
                result = future.result()
                enriched_results.append(result)
            except Exception:
                pass

    enriched_results.sort(key=lambda x: x.topic_id)

    return EvidenceExtractionResponse(enriched_feedback=enriched_results)


def _build_evidence_json(item: EnrichedFeedbackItem) -> str:
    evidence_obj = {
        "feedback_evidence": item.feedback_evidence or [],
        "antifeedback_evidence": item.antifeedback_evidence or [],
        "reasoning": item.reasoning or "",
    }
    return json.dumps(evidence_obj, indent=2)


def _judge_single_feedback(item: EnrichedFeedbackItem, role_context: RoleContext) -> JudgedFeedbackItem:
    prompt = JUDGE_PROMPT.format(
        role_title=role_context.role_title.strip() or "Not specified",
        experience_range=role_context.experience_range.strip() or "Not specified",
        must_have_skills=", ".join(role_context.must_have_skills) if role_context.must_have_skills else "Not specified",
        good_to_have_skills=", ".join(role_context.good_to_have_skills) if role_context.good_to_have_skills else "Not specified",
        job_description=role_context.job_description.strip() or "Not provided",
        intake_notes=role_context.intake_notes.strip() or "Not provided",
        topic=item.topic_heading,
        feedback=item.feedback,
        antifeedback=item.antifeedback,
        evidence_json=_build_evidence_json(item),
    )

    try:
        response = call_sonnet(prompt)
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
        )


@app.post("/judge-feedback", response_model=JudgeResponse)
def judge_feedback(request: JudgeRequest):
    role_context = request.role_context or RoleContext()

    judged_results = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(_judge_single_feedback, item, role_context)
            for item in request.enriched_feedback
        ]

        for future in as_completed(futures):
            try:
                result = future.result()
                judged_results.append(result)
            except Exception:
                pass

    judged_results.sort(key=lambda x: x.topic_id)

    return JudgeResponse(judged_feedback=judged_results, role_context_used=role_context)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {
        "message": "Interview Feedback Processing API",
        "endpoints": [
            "/map-topics",
            "/process-feedback",
            "/process-complete",
            "/extract-evidence",
            "/judge-feedback",
            "/health",
        ],
    }
