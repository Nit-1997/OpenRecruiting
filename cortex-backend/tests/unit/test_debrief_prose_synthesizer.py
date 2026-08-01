"""Unit tests for `ProseSynthesizer` (spec §7 — the single bounded LLM pass).

The `ConceptExtractor` is MOCKED (`AsyncMock`) so no network is touched. Coverage:

- valid JSON → prose mapped onto `ProseBundle`, scores/ranks/verdicts untouched.
- `{}` (invalid/non-JSON sentinel) → complete deterministic-template fallback.
- exception inside `extract` → complete deterministic fallback, NO raise.
- hallucinated candidate_id / unknown matrix dimension / out-of-range theme index
  → that field falls back; valid sibling fields are kept.
- empty candidate list → still a complete, valid `ProseBundle`.

`synthesize` MUST NEVER RAISE — the orchestrator depends on it (PINNED contract).
"""

from unittest.mock import AsyncMock

import pytest

from src.model.debrief import (
    CandidateSpine,
    CellScore,
    DebriefPanelVote,
    DebriefSourceStats,
    DebriefSpine,
    DebriefTheme,
    NextStep,
    ProseBundle,
)
from src.service.concept_extractor import ConceptExtractor
from src.service.debrief.prose_synthesizer import ProseSynthesizer


# ---------------------------------------------------------------------------
# Spine fixtures
# ---------------------------------------------------------------------------
def _candidate(
    candidate_id: str = "c1",
    name: str = "Ada Lovelace",
    rank: int = 1,
    verdict: str = "hire",
    cells: list[CellScore] | None = None,
    aggregate_score: float = 3.6,
    top_strengths: list[str] | None = None,
    top_concerns: list[str] | None = None,
    panel_votes: list[DebriefPanelVote] | None = None,
) -> CandidateSpine:
    return CandidateSpine(
        candidate_id=candidate_id,
        name=name,
        rounds_completed=3,
        rounds_total=4,
        cells=cells
        if cells is not None
        else [
            CellScore(candidate_id=candidate_id, dimension="Python", value=3.8, is_must_have=True),
            CellScore(candidate_id=candidate_id, dimension="System Design", value=3.0, is_must_have=False),
        ],
        aggregate_score=aggregate_score,
        rank=rank,
        verdict=verdict,
        panel_votes=panel_votes
        if panel_votes is not None
        else [DebriefPanelVote(panelist="Grace Hopper", panelist_role="Tech Screen", vote="yes")],
        top_strengths=top_strengths if top_strengths is not None else ["Python", "Communication"],
        top_concerns=top_concerns if top_concerns is not None else ["System Design depth"],
    )


def _spine(candidates: list[CandidateSpine] | None = None, **overrides) -> DebriefSpine:
    base = dict(
        org_id="org-1",
        requisition_id="req-1",
        role_title="Senior Backend Engineer",
        dimensions=["Python", "System Design"],
        must_have_dimensions={"Python"},
        candidates=candidates if candidates is not None else [_candidate()],
        themes=[
            DebriefTheme(label="Strong engineer", tone="pos", weight=0.9, evidence_count=4),
            DebriefTheme(label="Design gap", tone="neg", weight=0.4, evidence_count=2),
        ],
        source_stats=DebriefSourceStats(scorecards=3, transcripts=2),
        confidence="high",
        overall_verdict="hire",
        risks=["Limited system-design evidence."],
    )
    base.update(overrides)
    return DebriefSpine(**base)


def _synth(extract_return=None, extract_side_effect=None) -> ProseSynthesizer:
    extractor = AsyncMock(spec=ConceptExtractor)
    if extract_side_effect is not None:
        extractor.extract = AsyncMock(side_effect=extract_side_effect)
    else:
        extractor.extract = AsyncMock(return_value=extract_return if extract_return is not None else {})
    return ProseSynthesizer(extractor)


# ---------------------------------------------------------------------------
# 1. Valid JSON → prose mapped onto ProseBundle
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_valid_json_maps_prose():
    llm = {
        "per_candidate": {
            "c1": {"headline": "Top-tier backend engineer", "recommendation": "Advance to offer."}
        },
        "headline_recommendation": "Hire Ada; clear front-runner.",
        "risks": ["System-design depth is unproven."],
        "next_steps": [{"label": "Schedule final loop", "owner": "Recruiter", "due": "2026-06-12"}],
        "theme_labels": {"0": "Exceptional engineering", "1": "Design coaching needed"},
        "matrix_notes": {"Python": "Consistently strong across rounds."},
    }
    synth = _synth(extract_return=llm)
    bundle = await synth.synthesize(_spine())

    assert isinstance(bundle, ProseBundle)
    assert bundle.per_candidate["c1"]["headline"] == "Top-tier backend engineer"
    assert bundle.per_candidate["c1"]["recommendation"] == "Advance to offer."
    assert bundle.headline_recommendation == "Hire Ada; clear front-runner."
    assert bundle.risks == ["System-design depth is unproven."]
    assert bundle.next_steps[0].label == "Schedule final loop"
    assert bundle.next_steps[0].owner == "Recruiter"
    assert bundle.next_steps[0].due == "2026-06-12"
    assert bundle.theme_labels[0] == "Exceptional engineering"
    assert bundle.theme_labels[1] == "Design coaching needed"
    assert bundle.matrix_notes["Python"] == "Consistently strong across rounds."


@pytest.mark.asyncio
async def test_extract_called_with_spine_json_and_prompt():
    synth = _synth(extract_return={"per_candidate": {}})
    spine = _spine()
    await synth.synthesize(spine)

    synth._extractor.extract.assert_awaited_once()
    kwargs = synth._extractor.extract.await_args.kwargs
    # text must be a compact JSON string mentioning the candidate + dimension
    assert "c1" in kwargs["text"]
    assert "Python" in kwargs["text"]
    # prompt must forbid altering scores/ranks/verdicts
    prompt = kwargs["system_prompt"].lower()
    assert "score" in prompt and "rank" in prompt and "verdict" in prompt


# ---------------------------------------------------------------------------
# Addendum §6 — Cortex context is woven into the spine payload + prompt
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_payload_includes_enrichment_tier_and_cortex_signals():
    """Graph-enriched packet: the payload carries the enrichment tier + per-candidate
    Cortex signals (corroboration/contradictions) so the model can weave context."""
    import json

    cand = _candidate()
    cand.corroboration_count = 3
    cand.contradiction_count = 1
    cand.cortex_cell_count = 2
    synth = _synth(extract_return={"per_candidate": {}})
    spine = _spine(candidates=[cand], enrichment_tier="graph_enriched")
    await synth.synthesize(spine)

    text = synth._extractor.extract.await_args.kwargs["text"]
    payload = json.loads(text)
    assert payload["enrichment_tier"] == "graph_enriched"
    cand_payload = payload["candidates"][0]
    assert cand_payload["corroboration_count"] == 3
    assert cand_payload["contradiction_count"] == 1


@pytest.mark.asyncio
async def test_prompt_instructs_weaving_graph_context():
    synth = _synth(extract_return={})
    await synth.synthesize(_spine())
    prompt = synth._SYSTEM_PROMPT.lower()
    # The prompt must mention graph/corroboration context weaving.
    assert "corroborat" in prompt
    assert "graph" in prompt or "cortex" in prompt


# ---------------------------------------------------------------------------
# 2. {} → complete deterministic fallback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_dict_full_fallback():
    synth = _synth(extract_return={})
    bundle = await synth.synthesize(_spine())

    assert isinstance(bundle, ProseBundle)
    # every candidate has templated prose
    assert "c1" in bundle.per_candidate
    assert bundle.per_candidate["c1"]["headline"]  # non-empty
    assert "hire" in bundle.per_candidate["c1"]["headline"].lower()
    assert bundle.per_candidate["c1"]["recommendation"]
    assert bundle.headline_recommendation  # non-empty
    # risks fall back to spine.risks
    assert bundle.risks == ["Limited system-design evidence."]
    # theme labels fall back to spine theme labels
    assert bundle.theme_labels[0] == "Strong engineer"
    assert bundle.theme_labels[1] == "Design gap"
    # matrix notes present for each dimension
    assert set(bundle.matrix_notes.keys()) == {"Python", "System Design"}
    # next_steps has at least one sensible default
    assert len(bundle.next_steps) >= 1
    assert all(isinstance(s, NextStep) for s in bundle.next_steps)


# ---------------------------------------------------------------------------
# 3. exception in extract → complete fallback, no raise
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_extract_exception_full_fallback_no_raise():
    synth = _synth(extract_side_effect=RuntimeError("upstream 500"))
    bundle = await synth.synthesize(_spine())

    assert isinstance(bundle, ProseBundle)
    assert bundle.per_candidate["c1"]["headline"]
    assert bundle.headline_recommendation
    assert bundle.matrix_notes  # full deterministic bundle


# ---------------------------------------------------------------------------
# 4. partial hallucination → bad field falls back, good fields kept
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hallucinated_candidate_id_falls_back_keeps_valid():
    llm = {
        "per_candidate": {
            "c1": {"headline": "Real candidate headline", "recommendation": "Real rec."},
            "ghost": {"headline": "Hallucinated", "recommendation": "Should be dropped."},
        },
        "headline_recommendation": "Valid overall.",
        "matrix_notes": {"Python": "Valid note.", "Quantum Telepathy": "Unknown dim note."},
        "theme_labels": {"0": "Valid theme", "9": "Out-of-range theme"},
    }
    synth = _synth(extract_return=llm)
    bundle = await synth.synthesize(_spine())

    # real candidate kept
    assert bundle.per_candidate["c1"]["headline"] == "Real candidate headline"
    # hallucinated candidate dropped entirely
    assert "ghost" not in bundle.per_candidate
    # only real candidates present, all complete
    assert set(bundle.per_candidate.keys()) == {"c1"}
    # unknown dimension dropped, valid kept
    assert bundle.matrix_notes["Python"] == "Valid note."
    assert "Quantum Telepathy" not in bundle.matrix_notes
    # System Design (valid dim, no LLM note) gets a templated note
    assert "System Design" in bundle.matrix_notes
    # out-of-range theme index dropped, valid kept; theme 1 templated
    assert bundle.theme_labels[0] == "Valid theme"
    assert 9 not in bundle.theme_labels
    assert bundle.theme_labels[1] == "Design gap"


@pytest.mark.asyncio
async def test_candidate_missing_one_field_falls_back_that_field():
    llm = {
        "per_candidate": {
            "c1": {"headline": "Only a headline"}  # recommendation missing
        }
    }
    synth = _synth(extract_return=llm)
    bundle = await synth.synthesize(_spine())

    assert bundle.per_candidate["c1"]["headline"] == "Only a headline"
    # recommendation templated (non-empty)
    assert bundle.per_candidate["c1"]["recommendation"]


@pytest.mark.asyncio
async def test_malformed_next_steps_fall_back():
    llm = {"next_steps": [{"no_label": "x"}, "not-a-dict", {"label": "Good step"}]}
    synth = _synth(extract_return=llm)
    bundle = await synth.synthesize(_spine())

    labels = [s.label for s in bundle.next_steps]
    assert "Good step" in labels
    # malformed entries dropped; bundle still complete
    assert all(isinstance(s, NextStep) and s.label for s in bundle.next_steps)


# ---------------------------------------------------------------------------
# 5. empty candidates list → still a complete, valid bundle
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_candidates_complete_bundle():
    synth = _synth(extract_return={})
    bundle = await synth.synthesize(_spine(candidates=[], overall_verdict="mixed"))

    assert isinstance(bundle, ProseBundle)
    assert bundle.per_candidate == {}
    assert bundle.headline_recommendation  # still non-empty (deterministic)
    assert bundle.matrix_notes  # dimensions still present
    assert len(bundle.next_steps) >= 1


@pytest.mark.asyncio
async def test_no_themes_no_risks_no_crash():
    synth = _synth(extract_return={})
    bundle = await synth.synthesize(_spine(themes=[], risks=[]))

    assert isinstance(bundle, ProseBundle)
    assert bundle.theme_labels == {}
    # risks fall back to a deterministic default (non-empty) when spine has none
    assert isinstance(bundle.risks, list)


@pytest.mark.asyncio
async def test_strongest_dimension_in_templated_headline():
    """Deterministic headline names the candidate's strongest dimension."""
    cand = _candidate(
        cells=[
            CellScore(candidate_id="c1", dimension="Python", value=2.0, is_must_have=True),
            CellScore(candidate_id="c1", dimension="System Design", value=3.9, is_must_have=False),
        ],
    )
    synth = _synth(extract_return={})
    bundle = await synth.synthesize(_spine(candidates=[cand]))

    assert "System Design" in bundle.per_candidate["c1"]["headline"]
