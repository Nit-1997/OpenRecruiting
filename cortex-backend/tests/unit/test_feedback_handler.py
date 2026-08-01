import pytest

from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_strong_yes_produces_strong_in_edges(feedback_handler, mock_graphiti):
    payload = load_fixture("feedback_packet_strong_yes.json")
    triplets = feedback_handler.build_triplets_from_payload(payload, "org-001")

    competency_triplets = [t for t in triplets if t.target_type == "Competency"]
    assert len(competency_triplets) == 3
    for t in competency_triplets:
        assert t.relation == "STRONG_IN"
        assert t.edge_attributes["evidence_status"] == "from_rating"


@pytest.mark.asyncio
async def test_no_rating_produces_weak_in_edges(feedback_handler):
    payload = load_fixture("feedback_packet_no.json")
    triplets = feedback_handler.build_triplets_from_payload(payload, "org-001")

    competency_triplets = [t for t in triplets if t.target_type == "Competency"]
    assert len(competency_triplets) == 2
    for t in competency_triplets:
        assert t.relation == "WEAK_IN"


@pytest.mark.asyncio
async def test_maybe_rating_produces_assessed_on_edges(feedback_handler):
    payload = load_fixture("feedback_packet_maybe.json")
    triplets = feedback_handler.build_triplets_from_payload(payload, "org-001")

    competency_triplets = [t for t in triplets if t.target_type == "Competency"]
    assert len(competency_triplets) == 2
    for t in competency_triplets:
        assert t.relation == "ASSESSED_ON"


@pytest.mark.asyncio
async def test_interviewed_in_edge_created(feedback_handler):
    payload = load_fixture("feedback_packet_strong_yes.json")
    triplets = feedback_handler.build_triplets_from_payload(payload, "org-001")

    interview_triplets = [t for t in triplets if t.relation == "INTERVIEWED_IN"]
    assert len(interview_triplets) == 1
    assert interview_triplets[0].source_name == "Alice Johnson"
    assert interview_triplets[0].target_name == "System Design"
    assert interview_triplets[0].edge_attributes["rating"] == "strong_yes"


@pytest.mark.asyncio
async def test_interviewer_conducted_edge(feedback_handler):
    payload = load_fixture("feedback_packet_strong_yes.json")
    triplets = feedback_handler.build_triplets_from_payload(payload, "org-001")

    conducted_triplets = [t for t in triplets if t.relation == "CONDUCTED"]
    assert len(conducted_triplets) == 1
    assert conducted_triplets[0].source_name == "interviewer@example.com"
    assert conducted_triplets[0].source_attributes["interviewer_ref"] == "interviewer@example.com"


@pytest.mark.asyncio
async def test_null_interviewer_skips_conducted(feedback_handler):
    payload = load_fixture("feedback_packet_maybe.json")
    triplets = feedback_handler.build_triplets_from_payload(payload, "org-001")

    conducted_triplets = [t for t in triplets if t.relation == "CONDUCTED"]
    assert len(conducted_triplets) == 0


@pytest.mark.asyncio
async def test_competency_normalization_applied(feedback_handler):
    payload = load_fixture("feedback_packet_no.json")
    triplets = feedback_handler.build_triplets_from_payload(payload, "org-001")

    competency_names = [t.target_name for t in triplets if t.target_type == "Competency"]
    assert "Problem Solving" in competency_names
    assert "Code Quality" in competency_names


@pytest.mark.asyncio
async def test_round_category_normalization(feedback_handler):
    payload = load_fixture("feedback_packet_maybe.json")
    triplets = feedback_handler.build_triplets_from_payload(payload, "org-001")

    round_triplets = [t for t in triplets if t.target_type == "Round"]
    assert round_triplets[0].target_attributes["category"] == "behavioral"
