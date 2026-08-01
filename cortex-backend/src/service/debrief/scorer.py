"""DebriefScorer — the deterministic scoring spine (spec 2026-06-08). PURE: zero
I/O, fully unit-testable. Operates over the spine dataclasses only.

Scoring model (2026-06-08 rating-based addendum — supersedes the competency
aggregate/verdict/confidence of the 2026-06-07 spec):

- The comparative score is driven by `candidate_rounds.rating`, a 5-point panel
  decision per round (`strong_no 1 · no 2 · maybe 3 · yes 4 · strong_yes 5`,
  `rating_points`). A candidate's `rating_average` is the mean over their rated
  rounds; `rescale_to_four` maps it onto the FE 1–4 contract (`score_scale` stays
  4). `verdict_from_average` derives the verdict; `confidence_from_ratings` reads
  rating volume + panel disagreement (+ Cortex corroboration when present).
- The competency cell (`score_cell`) is now SUPPLEMENTAL — it populates the
  graph-enriched matrix only. `evidence_status` is no longer a standalone cell
  base (R7): with no Cortex standing it merely flags a contradiction; the value
  comes from a real graph standing (± the Supabase grounding adjustment) and/or an
  assessment score, else None.
"""

import math

import structlog

from src.model.debrief import (
    CellScore,
    CompetencyStanding,
)

logger = structlog.get_logger(__name__)

# §6.2 step 1 — base value per Cortex (graph) standing label (enriched matrix only).
_STANDING_BASE: dict[str, float] = {
    "STRONG_IN": 4.0,
    "ASSESSED_ON": 2.5,
    "WEAK_IN": 1.5,
    "DEMONSTRATED": 3.5,  # skill edge, STRONG-leaning
    "CLAIMED": 2.0,  # skill edge, ASSESSED-leaning
}

# Addendum §4 — Supabase evidence_status ADJUSTMENT, applied to the Cortex base
# when a graph standing leads the cell. `supported` is a REAL prod value (+0.25),
# NOT unknown. Unrecognized statuses normalize to `partial` (0.0) before lookup.
_EVIDENCE_ADJUSTMENT: dict[str, float] = {
    "verified": 0.5,
    "supported": 0.25,
    "partial": 0.0,
    "none": -0.25,
    "contradicted": -1.0,
}

# Known evidence_status vocabulary (addendum §4). Anything else → `partial`.
_KNOWN_EVIDENCE_STATUSES = frozenset(_EVIDENCE_ADJUSTMENT)

# R2 (2026-06-08) — candidate_rounds.rating → 5-point ordinal. The spine score.
_RATING_POINTS: dict[str, int] = {
    "strong_no": 1,
    "no": 2,
    "maybe": 3,
    "yes": 4,
    "strong_yes": 5,
}

_CELL_FLOOR = 1.0
_CELL_CEIL = 4.0


class DebriefScorer:
    """Rating-based aggregate/verdict/confidence (the spine) + the supplemental
    §6.2 competency cell scoring + §6.3 rank. Stateless and pure — every method is
    a function of its arguments."""

    # ------------------------------------------------------------------ #
    # Rating spine (2026-06-08 §2/§4) — the primary comparative score
    # ------------------------------------------------------------------ #
    @staticmethod
    def rating_points(rating: str | None) -> int | None:
        """`candidate_rounds.rating` → its 5-point ordinal, or None for an
        unknown/absent rating (excluded from the average — not scorable)."""
        return _RATING_POINTS.get(rating) if rating is not None else None

    def rating_average(self, ratings: list[str | None]) -> float | None:
        """Mean of the VALID 5-point ratings across a candidate's rated rounds.
        Returns None when no round carries a usable rating (the candidate is then
        not scorable — eligibility should already exclude this case)."""
        points = [p for p in (self.rating_points(r) for r in ratings) if p is not None]
        if not points:
            return None
        return sum(points) / len(points)

    def rescale_to_four(self, avg_five: float) -> float:
        """Map a 1..5 rating average onto the FE 1..4 contract (R4):
        `1 + (avg-1)·3/4`, clamped [1,4], rounded to 1 decimal. `score_scale`
        stays 4 so the FE render contract is unchanged."""
        return round(self._clamp(1.0 + (avg_five - 1.0) * 0.75), 1)

    @staticmethod
    def verdict_from_average(avg_five: float | None) -> str:
        """§4 verdict bands on the 1..5 rating average. None (no rated rounds) →
        honest `mixed`, never a fabricated hire/no_hire."""
        if avg_five is None:
            return "mixed"
        if avg_five >= 4.25:
            return "strong_hire"
        if avg_five >= 3.5:
            return "hire"
        if avg_five >= 2.5:
            return "mixed"
        return "no_hire"

    def confidence_from_ratings(
        self,
        ratings: list[str | None],
        corroboration_count: int,
        must_have_count: int,
    ) -> str:
        """§4 confidence from evidence VOLUME + panel DISAGREEMENT (not from
        evidence_status):
        - `high`  — ≥3 rated rounds AND low disagreement (rating spread ≤ 1) AND,
                    when Cortex must-haves exist, corroboration on ≥ half of them.
        - `low`   — only 1 rated round OR high disagreement (spread ≥ 3, e.g. a
                    strong_yes next to a strong_no).
        - `medium`— otherwise.
        A split panel correctly reads low-confidence — something the old
        coverage-based model could not express."""
        points = [p for p in (self.rating_points(r) for r in ratings) if p is not None]
        if not points:
            return "low"
        n = len(points)
        spread = max(points) - min(points)
        corroborates = must_have_count == 0 or (
            corroboration_count >= math.ceil(must_have_count / 2)
        )
        if n >= 3 and spread <= 1 and corroborates:
            return "high"
        if n <= 1 or spread >= 3:
            return "low"
        return "medium"

    # ------------------------------------------------------------------ #
    # Competency cell (supplemental — graph-enriched matrix only)
    # ------------------------------------------------------------------ #
    def score_cell(
        self,
        standing: CompetencyStanding | None,
        assessment_score: float | None,
        is_must_have: bool,
    ) -> CellScore:
        """Resolve a supplemental competency cell value in [1,4] or None for one
        (candidate, dimension) — used to populate the graph-enriched matrix:

        1. Cortex lead present (graph standing label) → base from the label, then
           apply the Supabase `evidence_status` ADJUSTMENT (grounding). A Supabase
           `contradicted` pulls a confident Cortex cell down + flags it.
        2. Cortex silent → evidence_status alone NO LONGER bases a value (R7); only
           an assessment score (normalized ×4/5) does. Neither → None.
        3. Assessment + graph lead both present → averaged.
        Clamp [1,4], round 1 decimal.

        `standing.evidence_status` carries the Supabase grounding status; a
        `contradicted` sets the flag even when no numeric value survives (so the
        contradiction still surfaces as a risk)."""
        candidate_id = standing.candidate_id if standing is not None else ""
        dimension = standing.dimension if standing is not None else ""
        raw_status = standing.evidence_status if standing is not None else None
        status = self._normalize_status(raw_status)

        # Contradiction flag tracks the NORMALIZED status, so an unknown status
        # (→ partial) never spuriously flags a contradiction.
        contradicted = status == "contradicted"

        # The "lead" value: Cortex base + Supabase adjustment when a graph standing
        # leads; else None (evidence_status alone no longer bases a value — R7).
        lead_value = self._lead_value(standing, status)

        # Assessment (1..5 → score*4/5), averaged with the lead value when present.
        assessment_value = (assessment_score * 4.0 / 5.0) if assessment_score is not None else None

        value = self._blend(lead_value, assessment_value)
        if value is not None:
            value = round(self._clamp(value), 1)

        return CellScore(
            candidate_id=candidate_id,
            dimension=dimension,
            value=value,
            is_must_have=is_must_have,
            contradicted=contradicted,
        )

    def rank(self, candidates: list["CandidateSpine"]) -> list["CandidateSpine"]:
        """§6.3: sort by aggregate_score desc (the rating-based spine), tie-breaks →
        must-have coverage % → corroboration count → fewest contradictions. Assigns
        1-based `rank` in place; returns the pre-sorted list (index 0 = winner)."""
        ordered = sorted(
            candidates,
            key=lambda c: (
                c.aggregate_score,
                c.must_have_coverage_pct,
                c.corroboration_count,
                -c.contradiction_count,  # fewer contradictions ranks higher
            ),
            reverse=True,
        )
        for index, candidate in enumerate(ordered, start=1):
            candidate.rank = index
        return ordered

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _normalize_status(raw_status: str | None) -> str | None:
        """Addendum §4 vocab normalization. A None status stays None (no signal);
        a recognized status passes through; anything else → `partial` (neutral) +
        a warning so unexpected vocab is visible without corrupting the score."""
        if raw_status is None:
            return None
        if raw_status in _KNOWN_EVIDENCE_STATUSES:
            return raw_status
        logger.warning("debrief_unknown_evidence_status", status=raw_status)
        return "partial"

    @staticmethod
    def _lead_value(standing: CompetencyStanding | None, status: str | None) -> float | None:
        """Competency lead value (supplemental, R7):
        - Cortex standing label present → its base + the Supabase status adjustment.
        - Otherwise → None. evidence_status alone NO LONGER bases a value; a cell
          with only a status (no standing, no assessment) is empty (em-dash)."""
        label = standing.standing if standing is not None else None
        cortex_base = _STANDING_BASE.get(label) if label is not None else None

        if cortex_base is not None:
            adjustment = _EVIDENCE_ADJUSTMENT.get(status or "", 0.0)
            return cortex_base + adjustment

        return None

    @staticmethod
    def _blend(lead_value: float | None, assessment_value: float | None) -> float | None:
        """Average lead + assessment when both present; otherwise whichever exists;
        None when neither has evidence."""
        if lead_value is not None and assessment_value is not None:
            return (lead_value + assessment_value) / 2.0
        if lead_value is not None:
            return lead_value
        return assessment_value  # None when both are None

    @staticmethod
    def _clamp(value: float) -> float:
        return max(_CELL_FLOOR, min(_CELL_CEIL, value))
