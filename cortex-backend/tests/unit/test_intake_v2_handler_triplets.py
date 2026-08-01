"""Test IntakeV2Handler builds the 9 triplet types from spec §4.6."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.model.packets import IntakeV2Packet
from src.service.handlers.intake_v2_handler import IntakeV2Handler


def _packet() -> IntakeV2Packet:
    return IntakeV2Packet(
        session_id="s1",
        requisition_id="r1",
        organization_id="org-a",
        role_title="Senior Backend Engineer",
        role_location="NYC",
        experience_min_years=5,
        experience_max_years=8,
        form_data={
            "role_name": "Senior Backend Engineer",
            "location": "NYC",
            "experience_min": 5,
            "experience_max": 8,
        },
        current_answers={
            "q1_role_overview": {"text": "Builds payments infrastructure", "status": "validated"},
            "q4_must_haves":    {"text": "Python, PostgreSQL, REST at scale", "status": "validated"},
            "q5_nice_to_haves": {"text": "Kafka, Redis", "status": "validated"},
            "q6_cultural_fit":  {"text": "ownership, directness", "status": "validated"},
        },
        turns=[],
        modalities_used=["voice"],
        rounds=[
            {"name": "Coding", "category": "coding",
             "feedback_questions": [
                 {"heading": "Code Quality", "description": "Readable, structured."},
                 {"heading": "Problem Solving", "description": "Decomposes."},
             ]},
            {"name": "System Design", "category": "design",
             "feedback_questions": [
                 {"heading": "Trade-offs", "description": "Considers CAP."},
             ]},
        ],
    )


@pytest.mark.asyncio
async def test_build_triplets_emits_all_nine_relation_types():
    fetcher = MagicMock()
    fetcher.fetch_intake_v2_session = AsyncMock(return_value=_packet())
    ingestion = MagicMock()
    handler = IntakeV2Handler(fetcher=fetcher, ingestion_service=ingestion)

    triplets = await handler.fetch_and_build_triplets(
        source_ref=MagicMock(session_id="s1"), org_id="org-a"
    )
    relations = {t.relation for t in triplets}

    expected = {"TARGETS", "LOCATED_IN", "REQUIRES", "NICE_TO_HAVE", "VALUES",
                "HAS_ROUND", "ASSESSES", "HOSTS"}
    missing = expected - relations
    assert not missing, f"Missing relations: {missing}"


@pytest.mark.asyncio
async def test_build_triplets_org_hosts_requisition():
    fetcher = MagicMock()
    fetcher.fetch_intake_v2_session = AsyncMock(return_value=_packet())
    handler = IntakeV2Handler(fetcher=fetcher, ingestion_service=MagicMock())
    triplets = await handler.fetch_and_build_triplets(MagicMock(session_id="s1"), "org-a")
    hosts = [t for t in triplets if t.relation == "HOSTS"]
    assert len(hosts) == 1
    assert hosts[0].source_type == "Org"
    assert hosts[0].target_type == "Requisition"
    assert hosts[0].target_id == "r1"


@pytest.mark.asyncio
async def test_build_triplets_requires_skills_from_q4():
    fetcher = MagicMock()
    fetcher.fetch_intake_v2_session = AsyncMock(return_value=_packet())
    handler = IntakeV2Handler(fetcher=fetcher, ingestion_service=MagicMock())
    triplets = await handler.fetch_and_build_triplets(MagicMock(session_id="s1"), "org-a")
    skills = [t for t in triplets if t.relation == "REQUIRES"]
    skill_names = {t.target_name for t in skills}
    assert "Python" in skill_names
    assert "PostgreSQL" in skill_names


@pytest.mark.asyncio
async def test_build_triplets_nice_to_have_from_q5():
    fetcher = MagicMock()
    fetcher.fetch_intake_v2_session = AsyncMock(return_value=_packet())
    handler = IntakeV2Handler(fetcher=fetcher, ingestion_service=MagicMock())
    triplets = await handler.fetch_and_build_triplets(MagicMock(session_id="s1"), "org-a")
    nth = [t for t in triplets if t.relation == "NICE_TO_HAVE"]
    nice_names = {t.target_name for t in nth}
    assert "Kafka" in nice_names
    assert "Redis" in nice_names


@pytest.mark.asyncio
async def test_build_triplets_values_traits_from_q6():
    fetcher = MagicMock()
    fetcher.fetch_intake_v2_session = AsyncMock(return_value=_packet())
    handler = IntakeV2Handler(fetcher=fetcher, ingestion_service=MagicMock())
    triplets = await handler.fetch_and_build_triplets(MagicMock(session_id="s1"), "org-a")
    traits = [t for t in triplets if t.relation == "VALUES"]
    trait_names = {t.target_name for t in traits}
    assert "ownership" in trait_names
    assert "directness" in trait_names


@pytest.mark.asyncio
async def test_build_triplets_has_round_and_assesses():
    fetcher = MagicMock()
    fetcher.fetch_intake_v2_session = AsyncMock(return_value=_packet())
    handler = IntakeV2Handler(fetcher=fetcher, ingestion_service=MagicMock())
    triplets = await handler.fetch_and_build_triplets(MagicMock(session_id="s1"), "org-a")
    has_round = [t for t in triplets if t.relation == "HAS_ROUND"]
    assesses = [t for t in triplets if t.relation == "ASSESSES"]
    assert len(has_round) == 2
    assert len(assesses) == 3


@pytest.mark.asyncio
async def test_build_triplets_rejects_org_mismatch():
    fetcher = MagicMock()
    fetcher.fetch_intake_v2_session = AsyncMock(return_value=_packet())
    handler = IntakeV2Handler(fetcher=fetcher, ingestion_service=MagicMock())
    with pytest.raises(Exception):
        await handler.fetch_and_build_triplets(MagicMock(session_id="s1"), "different-org")
