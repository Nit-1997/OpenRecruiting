"""Debrief skill data models.

Two layers live here:

1. **FE render contract** (Pydantic v2) — mirrors spec §4 of
   `docs/superpowers/specs/2026-06-07-debrief-agent-design.md` EXACTLY. The
   `DebriefPacket` this skill emits is rendered by recruiter-app's `packet-view.tsx`
   with ZERO shape translation, so field names and the `Literal[...]` enum sets
   must match the FE TS literal sets verbatim. Enums are validated server-side.

2. **Internal scoring spine** (`@dataclass`) — the deterministic structures the
   §6 scorer, §6.6 theme builder and §7 prose pass operate over. These never
   cross the HTTP boundary; only `DebriefPacket` does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enum literal sets — IDENTICAL to the FE TS unions (spec §4). Do not reorder
# or rename; the FE styles off exhaustive Records keyed on these exact strings.
# ---------------------------------------------------------------------------
DebriefVerdict = Literal["strong_hire", "hire", "mixed", "no_hire"]
DebriefVote = Literal["strong_yes", "yes", "maybe", "no", "strong_no"]
DebriefThemeTone = Literal["pos", "neg", "neu"]
DebriefConfidence = Literal["low", "medium", "high"]
# 'generating'/'failed' are backend-only and never appear in a rendered packet.
DebriefStatus = Literal["fresh", "superseded"]


# ===========================================================================
# FE render contract (Pydantic v2) — spec §4
# ===========================================================================
class PanelMember(BaseModel):
    """A panelist on the role. `name` is the join key for `DebriefPanelVote.panelist`."""

    name: str
    role: str
    initials: str
    color: str  # avatar bg hex


class DebriefPanelVote(BaseModel):
    """One interviewer's vote on a candidate. `panelist` MUST equal some
    `PanelMember.name` or the FE renders the cell as an em-dash."""

    panelist: str
    panelist_role: str
    vote: DebriefVote
    rationale: str | None = None


class DebriefCandidateSnapshot(BaseModel):
    """Per-candidate column of the packet. PROSE fields (`headline`,
    `recommendation`) come from the §7 LLM pass; everything else is deterministic."""

    candidate_id: str
    name: str
    initials: str
    color: str  # avatar bg hex
    rank: int  # 1-based; candidates[0] == recommended winner
    verdict: DebriefVerdict
    headline: str  # PROSE
    aggregate_score: float  # e.g. 3.6
    score_scale: int = 4  # ALWAYS 4
    rounds_completed: int
    rounds_total: int
    top_strengths: list[str] = Field(default_factory=list)
    top_concerns: list[str] = Field(default_factory=list)
    recommendation: str  # PROSE
    panel_votes: list[DebriefPanelVote] = Field(default_factory=list)
    # Addendum §5: True when the candidate has ZERO scorable cells. The FE then
    # renders "insufficient"/"—" instead of the 0.0 sentinel `aggregate_score`.
    # Additive + backward-compatible (default False / absent).
    aggregate_insufficient: bool = False


class DebriefTheme(BaseModel):
    """A trait cluster across the candidate set. `weight` 0..1, sorts desc."""

    label: str
    tone: DebriefThemeTone
    weight: float
    evidence_count: int


class DebriefDecisionRow(BaseModel):
    """One matrix row (a dimension). A MISSING candidate key in `scores`
    renders an em-dash on the FE — never emit 0 for "no evidence"."""

    dimension: str
    scores: dict[str, float] = Field(default_factory=dict)  # candidate_id -> 1..4
    winner_ids: list[str] = Field(default_factory=list)
    note: str = ""  # PROSE (short)


class DebriefSourceStats(BaseModel):
    """Evidence volume behind the packet."""

    scorecards: int
    transcripts: int


class NextStep(BaseModel):
    """A recommended action. PROSE. `due` is an ISO date."""

    label: str
    owner: str | None = None
    due: str | None = None


class DebriefPacket(BaseModel):
    """The complete comparative decision packet (spec §4). Emitted verbatim to
    the FE. `candidates` are PRE-SORTED: index 0 is the recommended winner."""

    id: str
    requisition_id: str
    role_title: str
    title: str
    subtitle: str
    generated_at: str  # ISO
    generated_by: str  # "Scout debrief agent"
    status: DebriefStatus
    confidence: DebriefConfidence
    verdict: DebriefVerdict  # overall == top candidate's verdict
    headline_recommendation: str  # PROSE
    panel_members: list[PanelMember] = Field(default_factory=list)
    candidates: list[DebriefCandidateSnapshot] = Field(default_factory=list)
    source_stats: DebriefSourceStats
    themes: list[DebriefTheme] = Field(default_factory=list)
    decision_matrix: list[DebriefDecisionRow] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)  # PROSE
    next_steps: list[NextStep] = Field(default_factory=list)  # PROSE


# ===========================================================================
# Controller request (spec §8 / task D) — internal-secret POST body
# ===========================================================================
class DebriefRequest(BaseModel):
    """POST /api/v1/debrief body. `org_id` is supplied by the calling backend
    (derived from the recruiter JWT upstream); never trusted from an end user."""

    org_id: str
    requisition_id: str
    candidate_ids: list[str] = Field(min_length=1)


# ===========================================================================
# Internal scoring spine (@dataclass) — spec §5/§6/§6.6/§7
# ===========================================================================
# Tier literals for a resolved matrix dimension (addendum §3). Precedence
# (highest first): must_have > nice_to_have > assessed. Order in the matrix
# follows this same precedence.
DimensionTier = Literal["must_have", "nice_to_have", "assessed"]


@dataclass
class Dimension:
    """One resolved matrix dimension (addendum §3, `DimensionResolver` output).

    `name` is the display name (configured-skill casing preferred over a feedback
    heading); `tier` drives matrix ordering + aggregate weight; `canonical_key`
    (`casefold(collapse_whitespace(trim(name)))`) is the dedup key the scorer uses
    to match candidate feedback/standings to a dimension across sources."""

    name: str
    tier: DimensionTier
    canonical_key: str


@dataclass
class CandidateRoundFact:
    """One completed round for one candidate, sourced from Supabase (§6.6 panel
    votes + source stats). Carries the raw rating/summary/interviewer needed to
    build a `DebriefPanelVote` and the round-name dimension hints."""

    candidate_round_id: str  # candidate_rounds.id — the corroboration `_source_id`
    candidate_id: str
    round_id: str
    round_name: str  # → panelist_role / dimension hint
    round_category: str | None
    rating: str | None  # candidate_rounds.rating → DebriefVote (identity map)
    summary: str | None  # candidate_rounds.summary → rationale seed (trimmed)
    interviewer_email: str | None
    interviewer_name: str | None  # → DebriefPanelVote.panelist / PanelMember.name
    has_feedback: bool  # completed + feedback present (scorecard counted)
    has_transcript: bool  # a transcripts row exists for this round


@dataclass
class CompetencyStanding:
    """A candidate's standing on ONE dimension as read from the graph (§6.2 step
    1+2) blended with Supabase assessment scores (§6.2 step 3). One per
    (candidate, dimension) where any signal exists."""

    candidate_id: str
    dimension: str  # canonical Competency/Skill concept-node name
    standing: str | None  # 'STRONG_IN' | 'ASSESSED_ON' | 'WEAK_IN' | 'DEMONSTRATED' | 'CLAIMED' | None
    evidence_status: str | None  # 'verified'|'partial'|'none'|'contradicted' (graph/Supabase)
    assessment_score: float | None  # assessment_evaluations.score (1..5), pre-normalization
    weight: float | None  # edge weight from the competency/skill edge (graph)


@dataclass
class TraitObservation:
    """One live `EXHIBITS` edge from a candidate to a Trait concept node (§6.6
    themes + §6.5 corroboration). Org-singleton trait node => cross-candidate
    clustering keys on `trait`."""

    candidate_id: str
    trait: str  # Trait node name (org-singleton concept node)
    polarity: str | None  # Trait node `polarity`: 'positive'|'negative'|'neutral'|'contextual'
    weight: float | None  # EXHIBITS edge weight
    source_round_id: str | None  # edge `_source_id` (candidate_round) — distinct => independent obs
    interviewer_name: str | None  # conducting interviewer — differs => independent corroboration


@dataclass
class CellScore:
    """A single resolved matrix cell (candidate × dimension), §6.2 output.
    `value is None` => "no evidence" => renders em-dash, excluded from the
    aggregate denominator."""

    candidate_id: str
    dimension: str
    value: float | None  # clamped [1,4], 1-decimal, or None
    is_must_have: bool  # weight 2 vs 1 in §6.3 aggregate
    contradicted: bool = False  # drives a contradiction risk (§6.2 step 2)


@dataclass
class RoundRating:
    """One rated completed round → its normalized 1..4 value, for the BASELINE
    (round-decision) matrix (spec 2026-06-08 §3). `round_id` is the stable column
    key shared across candidates on the requisition; `round_name` is the display
    label; `value` is `candidate_rounds.rating` mapped to the FE 1..4 scale."""

    round_id: str
    round_name: str
    value: float


@dataclass
class CandidateSpine:
    """Everything §6/§6.6/§7 need to describe ONE candidate. Built by the
    orchestrator from scaffold + graph reads + scorer output."""

    candidate_id: str
    name: str
    rounds_completed: int
    rounds_total: int
    cells: list[CellScore] = field(default_factory=list)  # one per matrix dimension (value may be None)
    # Per-rated-round normalized rating, for the baseline round-decision matrix
    # (2026-06-08 §3). Empty in the graph-enriched tier (competency matrix used).
    round_ratings: list[RoundRating] = field(default_factory=list)
    aggregate_score: float = 0.0  # §6.3
    rank: int = 0  # §6.3, 1-based (filled after cross-candidate sort)
    verdict: str = "mixed"  # §6.4 DebriefVerdict literal
    must_have_coverage_pct: float = 0.0  # §6.5 input + §6.4 tie-break
    corroboration_count: int = 0  # §6.5 input + §6.3 tie-break
    contradiction_count: int = 0  # §6.5 input + §6.3 tie-break
    panel_votes: list[DebriefPanelVote] = field(default_factory=list)  # §6.6
    top_strengths: list[str] = field(default_factory=list)  # §6.6 (ThemeBuilder)
    top_concerns: list[str] = field(default_factory=list)  # §6.6 (ThemeBuilder)
    trait_observations: list[TraitObservation] = field(default_factory=list)  # raw, for themes/strengths
    # True when the candidate has ZERO scorable cells (addendum §5): the
    # aggregate_score 0.0 is an honest "insufficient" sentinel (not a real /4),
    # and the verdict is derived from the panel rating, not forced to no_hire.
    aggregate_insufficient: bool = False
    cortex_cell_count: int = 0  # # cells Cortex (graph standing) contributed to (addendum §2 density)


@dataclass
class DebriefSpine:
    """The fully-assembled deterministic spine for the whole packet — the single
    fixed input to the §7 LLM pass and to `PacketBuilder`. No prose yet."""

    org_id: str
    requisition_id: str
    role_title: str
    dimensions: list[str] = field(default_factory=list)  # ordered matrix rows (must-have first)
    must_have_dimensions: set[str] = field(default_factory=set)  # subset of `dimensions`
    candidates: list[CandidateSpine] = field(default_factory=list)  # PRE-RANKED (index 0 = winner)
    panel_members: list[PanelMember] = field(default_factory=list)  # §6.6 (union of round interviewers)
    themes: list[DebriefTheme] = field(default_factory=list)  # §6.6 (ThemeBuilder)
    source_stats: DebriefSourceStats = field(  # §6.6
        default_factory=lambda: DebriefSourceStats(scorecards=0, transcripts=0)
    )
    confidence: str = "medium"  # §6.5 DebriefConfidence literal (overall)
    overall_verdict: str = "mixed"  # §6.4 top candidate's verdict (DebriefVerdict literal)
    risks: list[str] = field(default_factory=list)  # §6.6 deterministic risk/gap seeds (LLM polishes)
    # Enrichment tier (addendum §2): 'graph_enriched' when Cortex density is
    # present, else 'baseline'. Surfaced in the packet subtitle by PacketBuilder.
    enrichment_tier: str = "baseline"  # 'baseline' | 'graph_enriched'
    # cortex_density = (#cells Cortex contributed to) + (#themes) + (#corroborations)
    # (addendum §2/§5); the tier derives from this being > 0.
    cortex_density: int = 0


@dataclass
class ScaffoldData:
    """Supabase ground-truth scaffold (§5 Supabase rows). Produced by
    `SupabaseScaffold.build`; consumed by the orchestrator + graph reader +
    scorer. Holds requisition identity, the must-have/nice-to-have dimension
    seeds, per-candidate round facts, the panel, and source counts."""

    org_id: str
    requisition_id: str
    role_title: str
    must_have_skills: list[str] = field(default_factory=list)  # requisitions.must_have_skills
    nice_to_have_skills: list[str] = field(default_factory=list)  # requisitions.good_to_have_skills
    candidate_names: dict[str, str] = field(default_factory=dict)  # candidate_id -> name
    round_facts: list[CandidateRoundFact] = field(default_factory=list)  # all completed rounds across the set
    rounds_total_by_candidate: dict[str, int] = field(default_factory=dict)  # candidate_id -> total rounds
    # candidate_id -> {dimension -> assessment_evaluations.score (1..5)}; §6.2 step 3
    assessment_scores: dict[str, dict[str, float]] = field(default_factory=dict)
    # candidate_id -> {dimension -> evidence_status}; §6.2 step 2 (Supabase side)
    evidence_status: dict[str, dict[str, str]] = field(default_factory=dict)
    # Distinct, trimmed feedback_question.heading set across the selected
    # candidates' completed rounds (addendum §3 source 2 → tier `assessed`).
    feedback_headings: list[str] = field(default_factory=list)
    # candidate_id -> most-recent completed-round rating (addendum §5 verdict
    # fallback when a candidate has zero scorable cells). Identity-mapped to a
    # DebriefVote downstream; unknown ratings ignored.
    latest_rating_by_candidate: dict[str, str] = field(default_factory=dict)
    scorecard_count: int = 0  # §6.6 source_stats.scorecards
    transcript_count: int = 0  # §6.6 source_stats.transcripts


# ===========================================================================
# §7 LLM-pass output bundle (internal) — prose only, validated before use
# ===========================================================================
@dataclass
class ProseBundle:
    """The validated output of the single §7 LLM pass — PROSE ONLY. Every field
    here is grounded in `DebriefSpine`; on LLM failure each falls back to a
    deterministic template so the packet is always complete."""

    # candidate_id -> {"headline": str, "recommendation": str}
    per_candidate: dict[str, dict[str, str]] = field(default_factory=dict)
    headline_recommendation: str = ""  # overall PROSE
    risks: list[str] = field(default_factory=list)  # PROSE
    next_steps: list[NextStep] = field(default_factory=list)  # PROSE
    theme_labels: dict[int, str] = field(default_factory=dict)  # theme_index -> polished label
    matrix_notes: dict[str, str] = field(default_factory=dict)  # dimension -> short PROSE note
