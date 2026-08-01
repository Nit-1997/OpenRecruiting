"""Verify IntakeV2Handler calls Graphiti add_episode with formatted transcript + metadata."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.model.packets import IntakeV2Packet
from src.service.handlers.intake_v2_handler import (
    IntakeV2Handler,
    _format_transcript_for_episode,
)


def _packet_with_turns() -> IntakeV2Packet:
    return IntakeV2Packet(
        session_id="s1",
        requisition_id="r1",
        organization_id="org-a",
        role_title="Senior BE",
        form_data={"role_name": "Senior BE", "location": "NYC",
                   "experience_min": 5, "experience_max": 8},
        current_answers={
            "q4_must_haves": {"text": "Python", "status": "validated"},
        },
        turns=[
            {"role": "user", "content": "yeah we usually do 4 rounds",
             "modality": "voice", "idx": 0},
            {"role": "assistant", "content": "got it — what types?",
             "modality": "voice", "idx": 1},
            {"role": "user", "content": "actually let me add take-homes",
             "modality": "text", "idx": 2},
        ],
        modalities_used=["voice", "text"],
        duration_min=4.5,
        questions_version="v1-2026-05-27",
        rounds=[],
    )


def test_format_transcript_for_episode_marks_modality_and_role():
    out = _format_transcript_for_episode(_packet_with_turns().turns)
    assert "[Voice] Recruiter: yeah we usually do 4 rounds" in out
    assert "[Voice] Scout: got it" in out
    assert "[Text] Recruiter: actually let me add take-homes" in out


def test_format_transcript_skips_empty_content():
    out = _format_transcript_for_episode([
        {"role": "user", "content": "", "modality": "voice"},
        {"role": "user", "content": "  ", "modality": "voice"},
        {"role": "user", "content": "hi", "modality": "voice"},
    ])
    assert out == "[Voice] Recruiter: hi"


@pytest.mark.asyncio
async def test_handle_invokes_add_episode_with_metadata():
    fetcher = MagicMock()
    fetcher.fetch_intake_v2_session = AsyncMock(return_value=_packet_with_turns())

    ingestion = MagicMock()
    ingestion.ingest_triplets = AsyncMock(return_value=MagicMock(
        nodes_created=0, edges_created=0, errors=[]
    ))
    graphiti = MagicMock()
    graphiti.add_episode = AsyncMock()
    ingestion._graphiti = graphiti

    handler = IntakeV2Handler(fetcher=fetcher, ingestion_service=ingestion)
    src_ref = MagicMock(session_id="s1")

    result = await handler.handle(src_ref, org_id="org-a")

    graphiti.add_episode.assert_awaited_once()
    kwargs = graphiti.add_episode.await_args.kwargs
    assert kwargs["group_id"] == "org-a"
    assert "intake_v2:s1" in kwargs["name"]
    assert "r1" in kwargs["source_description"]
    assert "voice" in kwargs["source_description"]
    body = kwargs["episode_body"]
    assert "[Voice] Recruiter:" in body
    assert "[Text] Recruiter:" in body


@pytest.mark.asyncio
async def test_handle_skips_empty_transcript():
    fetcher = MagicMock()
    empty_packet = _packet_with_turns()
    empty_packet.turns = []
    fetcher.fetch_intake_v2_session = AsyncMock(return_value=empty_packet)

    ingestion = MagicMock()
    ingestion.ingest_triplets = AsyncMock(return_value=MagicMock(
        nodes_created=0, edges_created=0, errors=[]
    ))
    graphiti = MagicMock()
    graphiti.add_episode = AsyncMock()
    ingestion._graphiti = graphiti

    handler = IntakeV2Handler(fetcher=fetcher, ingestion_service=ingestion)
    await handler.handle(MagicMock(session_id="s1"), org_id="org-a")

    graphiti.add_episode.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_episode_failure_does_not_fail_overall():
    fetcher = MagicMock()
    fetcher.fetch_intake_v2_session = AsyncMock(return_value=_packet_with_turns())

    ingestion = MagicMock()
    ingestion.ingest_triplets = AsyncMock(return_value=MagicMock(
        nodes_created=2, edges_created=1, errors=[]
    ))
    graphiti = MagicMock()
    graphiti.add_episode = AsyncMock(side_effect=RuntimeError("Neo4j down"))
    ingestion._graphiti = graphiti

    handler = IntakeV2Handler(fetcher=fetcher, ingestion_service=ingestion)
    result = await handler.handle(MagicMock(session_id="s1"), org_id="org-a")

    assert any("episode write failed" in e for e in result.errors)
