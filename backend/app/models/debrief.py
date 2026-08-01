"""Debrief feature — request/response Pydantic models (backend orchestration).

Two groups live here:

1. **Render contract** — `DebriefPacketResponse` and its sub-models mirror spec §4
   of `docs/superpowers/specs/2026-06-07-debrief-agent-design.md` EXACTLY. The
   Cortex skill emits this shape; the backend persists the JSONB verbatim and
   returns it to recruiter-app's `packet-view.tsx` with ZERO shape translation. The
   `Literal[...]` enum sets are IDENTICAL to the FE TS unions — validating here
   guards the §4 contract from drift at the backend boundary.

2. **Orchestration DTOs** — `GenerateDebriefRequest`, the picker items
   (`RolePickItem`, `CandidatePickItem` + eligibility tier), and `PacketListItem`.

These models do NOT share code with the cortex-backend copy (the two services are
independent); they are deliberately re-declared so each service owns its contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enum literal sets — IDENTICAL to the FE TS unions (spec §4) and the cortex
# skill's DebriefPacket. Do not reorder/rename: the FE styles off exhaustive
# Records keyed on these exact strings.
# ---------------------------------------------------------------------------
DebriefVerdict = Literal["strong_hire", "hire", "mixed", "no_hire"]
DebriefVote = Literal["strong_yes", "yes", "maybe", "no", "strong_no"]
DebriefThemeTone = Literal["pos", "neg", "neu"]
DebriefConfidence = Literal["low", "medium", "high"]
# 'generating'/'failed' are backend-only (the debrief_packets.status column) and
# never appear inside a rendered packet body. 'draft' DOES reach the body: generate
# now lands a `draft` row WITH a packet, which the FE previews via GET /packets/{id}
# (the router overlays the row status onto the body) before committing via /save.
DebriefStatus = Literal["fresh", "superseded", "draft"]

# Eligibility tier for the candidate picker (spec §9.1).
EligibilityTier = Literal["ready", "awaiting_signal", "early_stage"]


# ===========================================================================
# §4 render contract
# ===========================================================================
class PanelMember(BaseModel):
    name: str
    role: str
    initials: str
    color: str  # avatar bg hex


class DebriefPanelVote(BaseModel):
    panelist: str  # MUST equal some PanelMember.name or the FE renders "—"
    panelist_role: str
    vote: DebriefVote
    rationale: str | None = None


class DebriefCandidateSnapshot(BaseModel):
    candidate_id: str
    name: str
    initials: str
    color: str
    rank: int  # 1-based; candidates[0] == recommended winner
    verdict: DebriefVerdict
    headline: str
    aggregate_score: float
    score_scale: int = 4  # ALWAYS 4
    rounds_completed: int
    rounds_total: int
    top_strengths: list[str] = Field(default_factory=list)
    top_concerns: list[str] = Field(default_factory=list)
    recommendation: str
    panel_votes: list[DebriefPanelVote] = Field(default_factory=list)
    # Addendum §5: True when the candidate has ZERO scorable cells; the FE renders
    # "insufficient"/"—" instead of the 0.0 aggregate. Additive/backward-compatible
    # so the pass-through model_validate doesn't drop the cortex skill's field.
    aggregate_insufficient: bool = False


class DebriefTheme(BaseModel):
    label: str
    tone: DebriefThemeTone
    weight: float  # 0..1, sorts desc
    evidence_count: int


class DebriefDecisionRow(BaseModel):
    dimension: str
    # candidate_id -> 1..4; a MISSING key renders an em-dash on the FE (never 0).
    scores: dict[str, float] = Field(default_factory=dict)
    winner_ids: list[str] = Field(default_factory=list)
    note: str = ""


class DebriefSourceStats(BaseModel):
    scorecards: int
    transcripts: int


class NextStep(BaseModel):
    label: str
    owner: str | None = None
    due: str | None = None  # ISO date


class DebriefPacketResponse(BaseModel):
    """The complete comparative decision packet (spec §4). `candidates` are
    PRE-SORTED: index 0 is the recommended winner. Returned verbatim to the FE."""

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
    headline_recommendation: str
    panel_members: list[PanelMember] = Field(default_factory=list)
    candidates: list[DebriefCandidateSnapshot] = Field(default_factory=list)
    source_stats: DebriefSourceStats
    themes: list[DebriefTheme] = Field(default_factory=list)
    decision_matrix: list[DebriefDecisionRow] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_steps: list[NextStep] = Field(default_factory=list)


# ===========================================================================
# Orchestration DTOs
# ===========================================================================
class GenerateDebriefRequest(BaseModel):
    """POST /api/v2/debrief/generate body. 2–5 candidates is enforced here at the
    schema boundary (FastAPI -> 422) AND re-checked in the service against org
    ownership + eligibility (the schema can't know either)."""

    requisition_id: str
    candidate_ids: list[str] = Field(min_length=2, max_length=5)


class RolePickItem(BaseModel):
    """A role in the role picker — only roles with >= 2 debrief-eligible
    candidates (spec §9.1)."""

    requisition_id: str
    role_title: str
    eligible_candidate_count: int


class CandidateSignal(BaseModel):
    """Per-candidate feedback-signal indicator for the picker (spec §7).

    The FE builds to this EXACT shape to gate selection + show "why ready/not":
      feedback_count        — total candidate_feedback rows across the candidate's
                              rounds (any round, not just completed ones).
      evidence_backed_count — of those, how many carry a non-null evidence_status
                              (verified/supported/partial/contradicted/none — i.e.
                              the feedback was graded, not a bare note).

    `has_graph_context` is intentionally omitted: it would require a Neo4j read,
    which backend must NOT perform (the Cortex graph lives behind the
    cortex-backend service). The cortex skill owns graph-derived signals.
    """

    feedback_count: int = 0
    evidence_backed_count: int = 0


class CandidatePickItem(BaseModel):
    """A candidate in the candidate picker, tagged with its eligibility tier and
    feedback signal. `ready` requires >= 1 completed round WITH a valid
    `candidate_rounds.rating` (the scoring signal, spec 2026-06-08 §5). The signal
    lets the FE show counts + gate not-ready candidates.

    `rated_round_count` is the number of completed, RATED rounds — the debrief
    averages over exactly these, so generate requires all selected candidates to
    share the same `rated_round_count` (the parity gate). The FE surfaces it so the
    recruiter can pick a parity-matched set."""

    candidate_id: str
    name: str
    eligibility: EligibilityTier
    rounds_completed: int
    rounds_total: int
    rated_round_count: int = 0
    signal: CandidateSignal = Field(default_factory=CandidateSignal)


class PacketListItem(BaseModel):
    """A row in the role-tab packet list (newest first). Thin — the full packet
    body is fetched on demand via GET /packets/{id}."""

    packet_id: str
    status: Literal["generating", "fresh", "superseded", "failed"]
    candidate_ids: list[str] = Field(default_factory=list)
    verdict: DebriefVerdict | None = None
    confidence: DebriefConfidence | None = None
    generated_at: str | None = None
    created_at: str


class GenerateDebriefResponse(BaseModel):
    """Response to POST /generate. Generate now lands a `draft` (the FE previews it,
    then commits via POST /packets/{id}/save). `generating` is still permitted for
    the transient pre-finalize state the FE may poll on GET /packets/{id}."""

    packet_id: str
    status: Literal["generating", "draft", "fresh", "superseded", "failed"]


class SaveDebriefResponse(BaseModel):
    """Response to POST /packets/{id}/save — the committed packet's new status
    (`fresh` on a successful commit or an idempotent re-save)."""

    packet_id: str
    status: Literal["fresh"]
