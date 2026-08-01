"""Unit tests for `DimensionResolver` (addendum §3 — tiered data sourcing).

PURE: no I/O, no async. The resolver unions + dedups + tiers + orders matrix
dimensions from THREE sources:
  1. Supabase requisition.must_have_skills (→ must_have), good_to_have (→ nice_to_have)
  2. Supabase distinct feedback_question.heading (→ assessed)
  3. graph REQUIRES (→ must_have) / ASSESSES (→ assessed)

Covered:
  * union of all three sources
  * dedup on canonical_key (casefold(collapse_whitespace(trim(name))))
  * normalization (case/whitespace variants collapse to one row)
  * tier precedence must_have > nice_to_have > assessed on conflict
  * order must_have → nice_to_have → assessed
  * 12-row cap
  * EMPTY-GRAPH: feedback headings alone produce a populated dimension set
  * non-empty whenever any feedback heading OR configured skill exists
"""

from src.model.debrief import Dimension, ScaffoldData
from src.service.debrief.dimension_resolver import DimensionResolver


def _scaffold(
    *,
    must_have: list[str] | None = None,
    nice_to_have: list[str] | None = None,
    feedback_headings: list[str] | None = None,
) -> ScaffoldData:
    return ScaffoldData(
        org_id="org-1",
        requisition_id="req-1",
        role_title="Product Manager",
        must_have_skills=must_have or [],
        nice_to_have_skills=nice_to_have or [],
        feedback_headings=feedback_headings or [],
    )


def _names(dims: list[Dimension]) -> list[str]:
    return [d.name for d in dims]


def _tier_of(dims: list[Dimension], canonical_key: str) -> str:
    return next(d.tier for d in dims if d.canonical_key == canonical_key)


# ---------------------------------------------------------------------------
# Union across all three sources
# ---------------------------------------------------------------------------
def test_unions_all_three_sources():
    scaffold = _scaffold(
        must_have=["Pricing"],
        nice_to_have=["SQL"],
        feedback_headings=["User Empathy"],
    )
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=["Roadmapping"])
    names = _names(dims)
    assert "Pricing" in names
    assert "SQL" in names
    assert "User Empathy" in names
    assert "Roadmapping" in names  # graph ASSESSES → assessed


def test_graph_dimensions_default_to_assessed_tier():
    scaffold = _scaffold()
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=["Roadmapping"])
    assert _tier_of(dims, "roadmapping") == "assessed"


# ---------------------------------------------------------------------------
# Dedup + normalization
# ---------------------------------------------------------------------------
def test_dedup_on_canonical_key_case_and_whitespace():
    # "Pricing" (must_have) and "  pricing " (heading) collapse to ONE row.
    scaffold = _scaffold(must_have=["Pricing"], feedback_headings=["  pricing "])
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=[])
    keys = [d.canonical_key for d in dims]
    assert keys.count("pricing") == 1
    assert len(dims) == 1


def test_canonical_key_collapses_internal_whitespace():
    scaffold = _scaffold(feedback_headings=["User   Empathy"])
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=[])
    assert dims[0].canonical_key == "user empathy"


def test_display_name_prefers_configured_skill_casing_over_heading():
    # Configured must_have "Pricing" wins the display name over a lowercase heading.
    scaffold = _scaffold(must_have=["Pricing"], feedback_headings=["pricing"])
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=[])
    assert dims[0].name == "Pricing"


# ---------------------------------------------------------------------------
# Tier precedence on conflict
# ---------------------------------------------------------------------------
def test_must_have_wins_over_assessed_when_same_concept():
    # A name that's both a must-have AND a feedback heading is must_have.
    scaffold = _scaffold(must_have=["Pricing"], feedback_headings=["Pricing"])
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=[])
    assert _tier_of(dims, "pricing") == "must_have"


def test_must_have_wins_over_nice_to_have():
    scaffold = _scaffold(must_have=["Pricing"], nice_to_have=["Pricing"])
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=[])
    assert _tier_of(dims, "pricing") == "must_have"


def test_nice_to_have_wins_over_assessed():
    scaffold = _scaffold(nice_to_have=["SQL"], feedback_headings=["SQL"])
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=[])
    assert _tier_of(dims, "sql") == "nice_to_have"


def test_graph_requires_is_must_have_tier():
    scaffold = _scaffold()
    dims = DimensionResolver().resolve(
        scaffold, graph_dimensions=[], graph_required=["Pricing"]
    )
    assert _tier_of(dims, "pricing") == "must_have"


# ---------------------------------------------------------------------------
# Ordering: must_have → nice_to_have → assessed
# ---------------------------------------------------------------------------
def test_order_is_must_have_then_nice_to_have_then_assessed():
    scaffold = _scaffold(
        must_have=["MustA"],
        nice_to_have=["NiceB"],
        feedback_headings=["AssessedC"],
    )
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=[])
    assert [d.tier for d in dims] == ["must_have", "nice_to_have", "assessed"]
    assert _names(dims) == ["MustA", "NiceB", "AssessedC"]


# ---------------------------------------------------------------------------
# 12-row cap
# ---------------------------------------------------------------------------
def test_caps_at_twelve_rows_keeping_highest_tiers():
    must = [f"M{i}" for i in range(10)]
    headings = [f"A{i}" for i in range(10)]
    scaffold = _scaffold(must_have=must, feedback_headings=headings)
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=[])
    assert len(dims) == 12
    # All 10 must-haves survive; only 2 assessed make the cut (must-have first).
    assert sum(1 for d in dims if d.tier == "must_have") == 10
    assert sum(1 for d in dims if d.tier == "assessed") == 2


# ---------------------------------------------------------------------------
# EMPTY-GRAPH → populated matrix from feedback headings (the core fix)
# ---------------------------------------------------------------------------
def test_empty_graph_feedback_headings_alone_populate_matrix():
    scaffold = _scaffold(
        feedback_headings=["User Empathy", "Pricing", "Product Sense"]
    )
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=[])
    assert len(dims) == 3
    assert all(d.tier == "assessed" for d in dims)
    assert set(_names(dims)) == {"User Empathy", "Pricing", "Product Sense"}


def test_non_empty_when_only_configured_skills_exist():
    scaffold = _scaffold(must_have=["Pricing"])
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=[])
    assert len(dims) == 1


def test_empty_everything_is_empty():
    dims = DimensionResolver().resolve(_scaffold(), graph_dimensions=[])
    assert dims == []


def test_blank_names_are_dropped():
    scaffold = _scaffold(must_have=["", "  "], feedback_headings=["Pricing"])
    dims = DimensionResolver().resolve(scaffold, graph_dimensions=[])
    assert _names(dims) == ["Pricing"]
