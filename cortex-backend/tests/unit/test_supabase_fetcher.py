from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.service.supabase_fetcher import SupabaseFetcher
from src.model.packets import EpisodicMetadata, IntakeMetadata


def _make_chain_mock(data: dict):
    """Build a mock that satisfies .table().select().eq().single().execute() chain."""
    execute_mock = AsyncMock(return_value=MagicMock(data=data))
    single_mock = MagicMock()
    single_mock.execute = execute_mock
    eq_mock = MagicMock()
    eq_mock.single = MagicMock(return_value=single_mock)
    select_mock = MagicMock()
    select_mock.eq = MagicMock(return_value=eq_mock)
    table_mock = MagicMock()
    table_mock.select = MagicMock(return_value=select_mock)
    return table_mock, execute_mock


def _make_multi_chain_mock(data: dict):
    """Build a mock for .table().select().eq().execute() (no .single())."""
    execute_mock = AsyncMock(return_value=MagicMock(data=data))
    eq_mock = MagicMock()
    eq_mock.execute = execute_mock
    select_mock = MagicMock()
    select_mock.eq = MagicMock(return_value=eq_mock)
    table_mock = MagicMock()
    table_mock.select = MagicMock(return_value=select_mock)
    return table_mock, execute_mock


@pytest.fixture
def fetcher():
    f = SupabaseFetcher()
    return f


def _make_full_episode_client(profile_data=None):
    """Return a mock AsyncClient that handles all tables for fetch_episodic_metadata."""
    cr_data = {
        "id": "cr-1",
        "candidate_id": "cand-1",
        "round_id": "round-1",
        "interviewer_email": "alice@example.com",
    }
    round_data = {"id": "round-1", "name": "Technical", "requisition_id": "req-1", "category": "technical"}
    req_data = {"id": "req-1", "role_title": "Engineer", "organization_id": "org-1"}
    cand_data = {"id": "cand-1", "name": "Bob Smith"}
    if profile_data is None:
        profile_data = {"full_name": "Alice Interviewer"}

    def make_single_chain(data):
        execute_mock = AsyncMock(return_value=MagicMock(data=data))
        single_mock = MagicMock()
        single_mock.execute = execute_mock
        eq_mock = MagicMock()
        eq_mock.single = MagicMock(return_value=single_mock)
        select_mock = MagicMock()
        select_mock.eq = MagicMock(return_value=eq_mock)
        table_mock = MagicMock()
        table_mock.select = MagicMock(return_value=select_mock)
        return table_mock

    def make_maybe_single_chain(data):
        execute_mock = AsyncMock(return_value=MagicMock(data=data))
        maybe_single_mock = MagicMock()
        maybe_single_mock.execute = execute_mock
        eq_mock = MagicMock()
        eq_mock.maybe_single = MagicMock(return_value=maybe_single_mock)
        select_mock = MagicMock()
        select_mock.eq = MagicMock(return_value=eq_mock)
        table_mock = MagicMock()
        table_mock.select = MagicMock(return_value=select_mock)
        return table_mock

    table_map = {
        "candidate_rounds": make_single_chain(cr_data),
        "rounds": make_single_chain(round_data),
        "requisitions": make_single_chain(req_data),
        "candidates": make_single_chain(cand_data),
        "profiles": make_maybe_single_chain(profile_data),
    }

    client = MagicMock()
    client.table = MagicMock(side_effect=lambda name: table_map[name])
    return client


@pytest.mark.asyncio
async def test_fetch_episodic_metadata_returns_correct_fields(fetcher):
    client = _make_full_episode_client()
    fetcher._client = client

    result = await fetcher.fetch_episodic_metadata("cr-1")

    assert isinstance(result, EpisodicMetadata)
    assert result.candidate_round_id == "cr-1"
    assert result.candidate_id == "cand-1"
    assert result.candidate_name == "Bob Smith"
    assert result.round_id == "round-1"
    assert result.round_name == "Technical"
    assert result.round_category == "technical"
    assert result.requisition_id == "req-1"
    assert result.role_title == "Engineer"
    assert result.organization_id == "org-1"
    assert result.interviewer_email == "alice@example.com"


@pytest.mark.asyncio
async def test_fetch_episodic_metadata_interviewer_ref_is_email(fetcher):
    client = _make_full_episode_client()
    fetcher._client = client

    result = await fetcher.fetch_episodic_metadata("cr-1")

    assert result.interviewer_ref == "alice@example.com"
    assert result.interviewer_name == "Alice Interviewer"


@pytest.mark.asyncio
async def test_fetch_episodic_metadata_interviewer_name_fallback_when_no_profile(fetcher):
    client = _make_full_episode_client()
    fetcher._client = client
    fetcher._interviewer_name_cache["alice@example.com"] = None

    result = await fetcher.fetch_episodic_metadata("cr-1")

    assert result.interviewer_ref == "alice@example.com"
    assert result.interviewer_name is None


@pytest.mark.asyncio
async def test_fetch_episodic_metadata_null_interviewer_email(fetcher):
    cr_data = {
        "id": "cr-2",
        "candidate_id": "cand-1",
        "round_id": "round-1",
        "interviewer_email": None,
    }
    round_data = {"id": "round-1", "name": "Phone Screen", "requisition_id": "req-1", "category": None}
    req_data = {"id": "req-1", "role_title": "Engineer", "organization_id": "org-1"}
    cand_data = {"id": "cand-1", "name": "Bob Smith"}

    def make_single_chain(data):
        execute_mock = AsyncMock(return_value=MagicMock(data=data))
        single_mock = MagicMock()
        single_mock.execute = execute_mock
        eq_mock = MagicMock()
        eq_mock.single = MagicMock(return_value=single_mock)
        select_mock = MagicMock()
        select_mock.eq = MagicMock(return_value=eq_mock)
        table_mock = MagicMock()
        table_mock.select = MagicMock(return_value=select_mock)
        return table_mock

    table_map = {
        "candidate_rounds": make_single_chain(cr_data),
        "rounds": make_single_chain(round_data),
        "requisitions": make_single_chain(req_data),
        "candidates": make_single_chain(cand_data),
    }
    client = MagicMock()
    client.table = MagicMock(side_effect=lambda name: table_map[name])
    fetcher._client = client

    result = await fetcher.fetch_episodic_metadata("cr-2")

    assert result.interviewer_email is None
    assert result.interviewer_ref is None


@pytest.mark.asyncio
async def test_fetch_interview_segments_returns_list(fetcher):
    segments = [
        {"participant": {"name": "Alice"}, "words": [{"text": "Hello"}]},
        {"participant": {"name": "Bob"}, "words": [{"text": "Hi"}]},
    ]
    data = {"segments": segments}

    execute_mock = AsyncMock(return_value=MagicMock(data=data))
    single_mock = MagicMock()
    single_mock.execute = execute_mock
    eq_mock = MagicMock()
    eq_mock.single = MagicMock(return_value=single_mock)
    select_mock = MagicMock()
    select_mock.eq = MagicMock(return_value=eq_mock)
    table_mock = MagicMock()
    table_mock.select = MagicMock(return_value=select_mock)

    client = MagicMock()
    client.table = MagicMock(return_value=table_mock)
    fetcher._client = client

    result = await fetcher.fetch_interview_segments("cr-1")
    assert result == segments


@pytest.mark.asyncio
async def test_fetch_interview_segments_returns_empty_list_on_null(fetcher):
    data = {"segments": None}

    execute_mock = AsyncMock(return_value=MagicMock(data=data))
    single_mock = MagicMock()
    single_mock.execute = execute_mock
    eq_mock = MagicMock()
    eq_mock.single = MagicMock(return_value=single_mock)
    select_mock = MagicMock()
    select_mock.eq = MagicMock(return_value=eq_mock)
    table_mock = MagicMock()
    table_mock.select = MagicMock(return_value=select_mock)

    client = MagicMock()
    client.table = MagicMock(return_value=table_mock)
    fetcher._client = client

    result = await fetcher.fetch_interview_segments("cr-1")
    assert result == []


@pytest.mark.asyncio
async def test_fetch_intake_transcript_returns_text(fetcher):
    data = {"intake_transcript": "Hello world transcript"}

    execute_mock = AsyncMock(return_value=MagicMock(data=data))
    single_mock = MagicMock()
    single_mock.execute = execute_mock
    eq_mock = MagicMock()
    eq_mock.single = MagicMock(return_value=single_mock)
    select_mock = MagicMock()
    select_mock.eq = MagicMock(return_value=eq_mock)
    table_mock = MagicMock()
    table_mock.select = MagicMock(return_value=select_mock)

    client = MagicMock()
    client.table = MagicMock(return_value=table_mock)
    fetcher._client = client

    result = await fetcher.fetch_intake_transcript("req-1")
    assert result == "Hello world transcript"


@pytest.mark.asyncio
async def test_fetch_question_summaries_returns_dict(fetcher):
    summaries = {"q1": "Good answer", "q2": "Needs improvement"}
    data = {"question_summaries": summaries}

    execute_mock = AsyncMock(return_value=MagicMock(data=data))
    single_mock = MagicMock()
    single_mock.execute = execute_mock
    eq_mock = MagicMock()
    eq_mock.single = MagicMock(return_value=single_mock)
    select_mock = MagicMock()
    select_mock.eq = MagicMock(return_value=eq_mock)
    table_mock = MagicMock()
    table_mock.select = MagicMock(return_value=select_mock)

    client = MagicMock()
    client.table = MagicMock(return_value=table_mock)
    fetcher._client = client

    result = await fetcher.fetch_question_summaries("cr-1")
    assert result == summaries


@pytest.mark.asyncio
async def test_fetch_question_summaries_returns_empty_dict_on_null(fetcher):
    data = {"question_summaries": None}

    execute_mock = AsyncMock(return_value=MagicMock(data=data))
    single_mock = MagicMock()
    single_mock.execute = execute_mock
    eq_mock = MagicMock()
    eq_mock.single = MagicMock(return_value=single_mock)
    select_mock = MagicMock()
    select_mock.eq = MagicMock(return_value=eq_mock)
    table_mock = MagicMock()
    table_mock.select = MagicMock(return_value=select_mock)

    client = MagicMock()
    client.table = MagicMock(return_value=table_mock)
    fetcher._client = client

    result = await fetcher.fetch_question_summaries("cr-1")
    assert result == {}


# ---------------------------------------------------------------------------
# Debrief scaffold fetcher methods — flexible chain mock (.select/.eq/.in_/.execute)
# ---------------------------------------------------------------------------
def _make_fluent_client(data):
    """A MagicMock AsyncClient whose .table(...).select(...).eq(...).in_(...).execute()
    chain returns `data`. Every builder method returns the same fluent object so call
    order doesn't matter for these tests."""
    builder = MagicMock()
    builder.select = MagicMock(return_value=builder)
    builder.eq = MagicMock(return_value=builder)
    builder.in_ = MagicMock(return_value=builder)
    builder.execute = AsyncMock(return_value=MagicMock(data=data))
    client = MagicMock()
    client.table = MagicMock(return_value=builder)
    return client, builder


@pytest.mark.asyncio
async def test_fetch_candidate_names_maps_id_to_name(fetcher):
    rows = [{"id": "c1", "name": "Ada"}, {"id": "c2", "name": "Brian"}]
    client, _ = _make_fluent_client(rows)
    fetcher._client = client
    result = await fetcher.fetch_candidate_names(["c1", "c2"])
    assert result == {"c1": "Ada", "c2": "Brian"}


@pytest.mark.asyncio
async def test_fetch_candidate_names_empty_input_no_query(fetcher):
    fetcher._client = MagicMock()  # would explode if used
    assert await fetcher.fetch_candidate_names([]) == {}


@pytest.mark.asyncio
async def test_fetch_candidate_rounds_for_requisition_returns_rows(fetcher):
    rows = [{"id": "cr1", "candidate_id": "c1", "round_id": "r1",
             "rounds": {"name": "Tech", "category": "technical", "requisition_id": "req-1"}}]
    client, builder = _make_fluent_client(rows)
    fetcher._client = client
    result = await fetcher.fetch_candidate_rounds_for_requisition("req-1", ["c1"])
    assert result == rows
    # filters: requisition (embedded), processing_status completed, candidate set
    builder.eq.assert_any_call("rounds.requisition_id", "req-1")
    builder.eq.assert_any_call("processing_status", "completed")
    builder.in_.assert_any_call("candidate_id", ["c1"])


@pytest.mark.asyncio
async def test_fetch_candidate_rounds_empty_candidates_short_circuits(fetcher):
    fetcher._client = MagicMock()
    assert await fetcher.fetch_candidate_rounds_for_requisition("req-1", []) == []


@pytest.mark.asyncio
async def test_fetch_assessment_scores_returns_rows(fetcher):
    rows = [{"candidate_round_id": "cr1", "category_name": "Leadership", "score": 4}]
    client, builder = _make_fluent_client(rows)
    fetcher._client = client
    result = await fetcher.fetch_assessment_scores(["cr1"])
    assert result == rows
    builder.in_.assert_any_call("candidate_round_id", ["cr1"])


@pytest.mark.asyncio
async def test_fetch_assessment_scores_empty_short_circuits(fetcher):
    fetcher._client = MagicMock()
    assert await fetcher.fetch_assessment_scores([]) == []


@pytest.mark.asyncio
async def test_fetch_evidence_status_by_dimension_returns_rows(fetcher):
    rows = [{"candidate_round_id": "cr1", "evidence_status": "verified",
             "feedback_questions": {"heading": "Leadership"}}]
    client, builder = _make_fluent_client(rows)
    fetcher._client = client
    result = await fetcher.fetch_evidence_status_by_dimension(["cr1"])
    assert result == rows
    builder.in_.assert_any_call("candidate_round_id", ["cr1"])


@pytest.mark.asyncio
async def test_fetch_evidence_status_empty_short_circuits(fetcher):
    fetcher._client = MagicMock()
    assert await fetcher.fetch_evidence_status_by_dimension([]) == []


@pytest.mark.asyncio
async def test_fetch_transcript_round_ids_returns_ids(fetcher):
    rows = [{"candidate_round_id": "cr1"}, {"candidate_round_id": "cr2"}, {"candidate_round_id": None}]
    client, _ = _make_fluent_client(rows)
    fetcher._client = client
    result = await fetcher.fetch_transcript_round_ids(["cr1", "cr2"])
    assert result == ["cr1", "cr2"]  # null dropped


@pytest.mark.asyncio
async def test_fetch_transcript_round_ids_empty_short_circuits(fetcher):
    fetcher._client = MagicMock()
    assert await fetcher.fetch_transcript_round_ids([]) == []
