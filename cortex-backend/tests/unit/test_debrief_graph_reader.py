"""Unit tests for DebriefGraphReader (spec §5 graph reads / §6.2 / §6.5 / §6.6).

These assert three independent things per read method:
1. The generated Cypher TEXT honours the graph conventions — `r.name = '<RELATION>'`,
   the tenant wall (`group_id` / `$org_id`), and the tombstone filter
   (`r.invalid_at IS NULL`).
2. Canned driver rows map into the correct dataclasses.
3. The defense-in-depth org guard drops/raises on a foreign `group_id` row, and an
   empty candidate list short-circuits without touching the driver.

The driver is a mock whose `execute_read` is an AsyncMock returning canned
`record.data()`-style dicts.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.model.debrief import CompetencyStanding, TraitObservation
from src.service.debrief.graph_reader import DebriefGraphReader, OrgScopeViolation

ORG = "org-123"
REQ = "req-abc"
CIDS = ["cand-1", "cand-2"]


def make_driver(*return_batches):
    """A mock Neo4jDriver whose execute_read returns each batch in turn.

    Each call records (query, parameters) so tests can assert on the query text.
    """
    driver = MagicMock()
    driver.execute_read = AsyncMock(side_effect=list(return_batches))
    return driver


def last_query(driver) -> str:
    return driver.execute_read.await_args.args[0]


def all_queries(driver) -> list[str]:
    return [call.args[0] for call in driver.execute_read.await_args_list]


# ---------------------------------------------------------------------------
# fetch_dimensions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fetch_dimensions_query_conventions():
    driver = make_driver([
        {"dimension": "Python", "gid": ORG},
        {"dimension": "System Design", "gid": ORG},
    ])
    reader = DebriefGraphReader(driver)

    out = await reader.fetch_dimensions(ORG, REQ)

    q = last_query(driver)
    assert "r.name = 'REQUIRES'" in q
    assert "r.name = 'ASSESSES'" in q
    assert "group_id" in q and "$org_id" in q
    assert "r.invalid_at IS NULL" in q
    # ref-prop addressing, never recomputed uuid5
    assert "requisition_ref: $req_id" in q
    params = driver.execute_read.await_args.kwargs.get("parameters") or driver.execute_read.await_args.args[1]
    assert params["org_id"] == ORG
    assert params["req_id"] == REQ
    assert out == ["Python", "System Design"]


@pytest.mark.asyncio
async def test_fetch_dimensions_dedupes_preserving_order():
    driver = make_driver([
        {"dimension": "Python", "gid": ORG},
        {"dimension": "Python", "gid": ORG},
        {"dimension": "System Design", "gid": ORG},
    ])
    reader = DebriefGraphReader(driver)
    assert await reader.fetch_dimensions(ORG, REQ) == ["Python", "System Design"]


@pytest.mark.asyncio
async def test_fetch_dimensions_org_guard_raises_on_foreign_row():
    driver = make_driver([
        {"dimension": "Python", "gid": ORG},
        {"dimension": "Leaked", "gid": "other-org"},
    ])
    reader = DebriefGraphReader(driver)
    with pytest.raises(OrgScopeViolation):
        await reader.fetch_dimensions(ORG, REQ)


@pytest.mark.asyncio
async def test_fetch_dimensions_drops_blank_names():
    driver = make_driver([
        {"dimension": "Python", "gid": ORG},
        {"dimension": None, "gid": ORG},
        {"dimension": "", "gid": ORG},
    ])
    reader = DebriefGraphReader(driver)
    assert await reader.fetch_dimensions(ORG, REQ) == ["Python"]


# ---------------------------------------------------------------------------
# fetch_competency_standings
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fetch_competency_standings_query_and_mapping():
    driver = make_driver([
        {
            "candidate_id": "cand-1",
            "dimension": "Python",
            "standing": "STRONG_IN",
            "evidence_status": "verified",
            "weight": 0.9,
            "gid": ORG,
        },
        {
            "candidate_id": "cand-2",
            "dimension": "System Design",
            "standing": "WEAK_IN",
            "evidence_status": None,
            "weight": None,
            "gid": ORG,
        },
    ])
    reader = DebriefGraphReader(driver)

    out = await reader.fetch_competency_standings(ORG, CIDS)

    q = last_query(driver)
    for rel in ("STRONG_IN", "WEAK_IN", "ASSESSED_ON", "DEMONSTRATED", "CLAIMED"):
        assert f"'{rel}'" in q
    assert "group_id" in q and "$org_id" in q
    assert "r.invalid_at IS NULL" in q
    assert "UNWIND $candidate_ids" in q
    assert "candidate_ref" in q

    assert len(out) == 2
    assert all(isinstance(s, CompetencyStanding) for s in out)
    first = out[0]
    assert first.candidate_id == "cand-1"
    assert first.dimension == "Python"
    assert first.standing == "STRONG_IN"
    assert first.evidence_status == "verified"
    assert first.weight == 0.9
    assert first.assessment_score is None  # graph reader never sources assessment scores
    assert out[1].standing == "WEAK_IN"
    assert out[1].weight is None


@pytest.mark.asyncio
async def test_fetch_competency_standings_empty_candidates_short_circuits():
    driver = make_driver()  # no batches; execute_read must never be awaited
    reader = DebriefGraphReader(driver)
    assert await reader.fetch_competency_standings(ORG, []) == []
    driver.execute_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_competency_standings_org_guard():
    driver = make_driver([
        {
            "candidate_id": "cand-1",
            "dimension": "Python",
            "standing": "STRONG_IN",
            "evidence_status": "verified",
            "weight": 0.9,
            "gid": "evil-org",
        }
    ])
    reader = DebriefGraphReader(driver)
    with pytest.raises(OrgScopeViolation):
        await reader.fetch_competency_standings(ORG, CIDS)


# ---------------------------------------------------------------------------
# fetch_trait_observations
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fetch_trait_observations_query_and_mapping():
    driver = make_driver([
        {
            "candidate_id": "cand-1",
            "trait": "Strong communicator",
            "polarity": "positive",
            "weight": 0.8,
            "source_round_id": "cr-1",
            "interviewer_name": "Alice",
            "gid": ORG,
        },
        {
            "candidate_id": "cand-1",
            "trait": "Shallow depth",
            "polarity": "negative",
            "weight": None,
            "source_round_id": None,
            "interviewer_name": None,
            "gid": ORG,
        },
    ])
    reader = DebriefGraphReader(driver)

    out = await reader.fetch_trait_observations(ORG, CIDS)

    q = last_query(driver)
    assert "r.name = 'EXHIBITS'" in q
    assert "group_id" in q and "$org_id" in q
    assert "r.invalid_at IS NULL" in q
    assert "UNWIND $candidate_ids" in q
    # polarity is a Trait NODE prop, not the edge
    assert ".polarity" in q
    assert "r.polarity" not in q

    assert len(out) == 2
    assert all(isinstance(o, TraitObservation) for o in out)
    obs = out[0]
    assert obs.candidate_id == "cand-1"
    assert obs.trait == "Strong communicator"
    assert obs.polarity == "positive"
    assert obs.weight == 0.8
    assert obs.source_round_id == "cr-1"
    assert obs.interviewer_name == "Alice"


@pytest.mark.asyncio
async def test_fetch_trait_observations_empty_candidates_short_circuits():
    driver = make_driver()
    reader = DebriefGraphReader(driver)
    assert await reader.fetch_trait_observations(ORG, []) == []
    driver.execute_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_trait_observations_org_guard():
    driver = make_driver([
        {
            "candidate_id": "cand-1",
            "trait": "Leaked trait",
            "polarity": "positive",
            "weight": 0.8,
            "source_round_id": "cr-1",
            "interviewer_name": "Mallory",
            "gid": "evil-org",
        }
    ])
    reader = DebriefGraphReader(driver)
    with pytest.raises(OrgScopeViolation):
        await reader.fetch_trait_observations(ORG, CIDS)


# ---------------------------------------------------------------------------
# fetch_corroboration (§6.5 — must-have-scoped, ≥2 distinct source rounds)
# ---------------------------------------------------------------------------
MUST_HAVE_NAMES = ["Python", "System Design"]


@pytest.mark.asyncio
async def test_fetch_corroboration_query_and_mapping():
    driver = make_driver([
        {"candidate_id": "cand-1", "corroboration_count": 2, "gid": ORG},
        {"candidate_id": "cand-2", "corroboration_count": 0, "gid": ORG},
    ])
    reader = DebriefGraphReader(driver)

    out = await reader.fetch_corroboration(ORG, CIDS, MUST_HAVE_NAMES)

    q = last_query(driver)
    assert "group_id" in q and "$org_id" in q
    assert "r.invalid_at IS NULL" in q
    assert "UNWIND $candidate_ids" in q
    assert "_source_id" in q  # independence keyed on distinct source rounds
    # Must-have-scoped: the concept name is filtered against the passed-in set.
    assert "$must_have_names" in q
    # The strict ≥2-distinct-interviewers AND-gate was dropped (interviewer
    # provenance is sparse); ≥2 distinct observing rounds IS the convergence test.
    assert "CONDUCTED" not in q

    params = (
        driver.execute_read.await_args.kwargs.get("parameters")
        or driver.execute_read.await_args.args[1]
    )
    assert params["must_have_names"] == MUST_HAVE_NAMES
    assert out == {"cand-1": 2, "cand-2": 0}


@pytest.mark.asyncio
async def test_fetch_corroboration_empty_candidates_short_circuits():
    driver = make_driver()
    reader = DebriefGraphReader(driver)
    assert await reader.fetch_corroboration(ORG, [], MUST_HAVE_NAMES) == {}
    driver.execute_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_corroboration_empty_must_have_short_circuits():
    """No must-have concepts to converge on → zero corroboration for everyone
    without touching the driver (counting is must-have-scoped, §6.5)."""
    driver = make_driver()
    reader = DebriefGraphReader(driver)
    assert await reader.fetch_corroboration(ORG, CIDS, []) == {c: 0 for c in CIDS}
    driver.execute_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_corroboration_org_guard():
    driver = make_driver([
        {"candidate_id": "cand-1", "corroboration_count": 3, "gid": "evil-org"},
    ])
    reader = DebriefGraphReader(driver)
    with pytest.raises(OrgScopeViolation):
        await reader.fetch_corroboration(ORG, CIDS, MUST_HAVE_NAMES)
