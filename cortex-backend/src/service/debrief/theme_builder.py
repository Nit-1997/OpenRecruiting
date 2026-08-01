"""ThemeBuilder — §6.6 theme clustering + per-candidate strengths/concerns +
risk/gap detection. PURE: zero I/O, fully unit-testable.

Clusters live `EXHIBITS` trait observations across the WHOLE candidate set into
ranked `DebriefTheme`s (trait nodes are org-singletons, so the trait NAME is a
safe cluster key), derives each candidate's top strengths/concerns from their own
trait signals + scored cells, and surfaces deterministic risk seeds
(contradictions + uncovered must-haves). The §7 LLM pass only polishes prose; it
never changes anything computed here.
"""

from src.model.debrief import (
    CandidateSpine,
    CellScore,
    DebriefTheme,
    TraitObservation,
)

# Polarity → FE theme tone (§6.6). Anything that isn't an explicit
# positive/negative signal (neutral, contextual, missing) reads as neutral.
_TONE_BY_POLARITY = {"positive": "pos", "negative": "neg"}

# Default edge weight for an observation with no recorded weight: a live edge is
# still real evidence, so it must contribute (never normalize a present theme to 0).
_DEFAULT_WEIGHT = 1.0

# How many strengths / concerns to keep per candidate (short, decision-relevant).
_MAX_PER_LIST = 3


class ThemeBuilder:
    """Clusters trait observations across the candidate set into ranked themes,
    derives each candidate's top strengths/concerns, and surfaces risks/gaps
    (contradictions + uncovered must-haves). Pure."""

    def build_themes(
        self,
        observations: list[TraitObservation],
        top_n: int = 8,
    ) -> list[DebriefTheme]:
        """§6.6: cluster `TraitObservation`s by Trait concept node across ALL
        selected candidates → `DebriefTheme` (tone from polarity:
        positive→'pos'/negative→'neg'/else→'neu'; `evidence_count` = distinct
        observing rounds; `weight` = normalized aggregate edge weight, 0..1).
        Return the top `top_n` by weight, sorted desc."""
        if not observations:
            return []

        # Cluster observations by trait name (org-singleton concept node).
        clusters: dict[str, list[TraitObservation]] = {}
        for obs in observations:
            clusters.setdefault(obs.trait, []).append(obs)

        # Aggregate raw edge weight per cluster (None weight counts as evidence).
        raw_weight = {
            trait: sum((o.weight if o.weight is not None else _DEFAULT_WEIGHT) for o in obs_list)
            for trait, obs_list in clusters.items()
        }
        max_weight = max(raw_weight.values())

        themes: list[DebriefTheme] = []
        for trait, obs_list in clusters.items():
            # Normalize into [0, 1]; the heaviest cluster anchors at 1.0.
            normalized = (raw_weight[trait] / max_weight) if max_weight > 0 else 0.0
            themes.append(
                DebriefTheme(
                    label=trait,
                    tone=self._tone_for(obs_list),
                    weight=round(normalized, 4),
                    evidence_count=self._distinct_rounds(obs_list),
                )
            )

        # Sort by weight desc, label asc as a stable deterministic tiebreak.
        themes.sort(key=lambda t: (-t.weight, t.label))
        return themes[:top_n]

    def strengths_and_concerns(
        self,
        candidate: CandidateSpine,
    ) -> tuple[list[str], list[str]]:
        """§6.6: from a candidate's highest-`weight` positive vs negative trait
        signals (plus contradicted scored cells), return `(top_strengths,
        top_concerns)` as short label lists. Deterministic seeds; the §7 LLM pass
        may polish phrasing."""
        # Order this candidate's traits by edge weight desc (None → default).
        ordered = sorted(
            candidate.trait_observations,
            key=lambda o: (o.weight if o.weight is not None else _DEFAULT_WEIGHT),
            reverse=True,
        )

        strengths: list[str] = []
        concerns: list[str] = []
        for obs in ordered:
            if obs.polarity == "positive":
                self._append_unique(strengths, obs.trait)
            elif obs.polarity == "negative":
                self._append_unique(concerns, obs.trait)

        # Contradicted scored cells are concerns even without a negative trait.
        for cell in candidate.cells:
            if cell.contradicted:
                self._append_unique(concerns, cell.dimension)

        return strengths[:_MAX_PER_LIST], concerns[:_MAX_PER_LIST]

    def risks_and_gaps(
        self,
        candidates: list[CandidateSpine],
        must_have_dimensions: set[str],
    ) -> list[str]:
        """§6.6/D6: surface deterministic risk seeds — contradicted cells
        (`CellScore.contradicted`) and uncovered must-have dimensions (a must-have
        with a `None`/absent cell) — as short strings. The §7 LLM pass polishes
        these. Deduped, stable order."""
        risks: list[str] = []
        for candidate in candidates:
            # Contradictions: an explicit conflict in the evidence.
            for cell in candidate.cells:
                if cell.contradicted:
                    self._append_unique(
                        risks,
                        f"Contradicted evidence on {cell.dimension} for {candidate.name}",
                    )

            # Gaps: a must-have with no scorable cell (None value or missing).
            for dimension in sorted(must_have_dimensions):
                cell = self.candidate_cells_for_dimension(candidate, dimension)
                if cell is None or cell.value is None:
                    self._append_unique(
                        risks,
                        f"No evidence for must-have {dimension} for {candidate.name}",
                    )
        return risks

    def candidate_cells_for_dimension(
        self,
        candidate: CandidateSpine,
        dimension: str,
    ) -> CellScore | None:
        """Helper: locate a candidate's `CellScore` for a dimension (or `None`).
        Used by `risks_and_gaps`/strengths derivation. Pure lookup."""
        for cell in candidate.cells:
            if cell.dimension == dimension:
                return cell
        return None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _tone_for(observations: list[TraitObservation]) -> str:
        """Trait nodes are org-singletons, so polarity is consistent within a
        cluster; take the first non-None polarity and map it, defaulting to 'neu'."""
        for obs in observations:
            if obs.polarity is not None:
                return _TONE_BY_POLARITY.get(obs.polarity, "neu")
        return "neu"

    @staticmethod
    def _distinct_rounds(observations: list[TraitObservation]) -> int:
        """Distinct observing rounds (§6.6). Falls back to the observation count
        when no round is attributed, so a live theme never reports 0 evidence."""
        rounds = {o.source_round_id for o in observations if o.source_round_id is not None}
        if rounds:
            return len(rounds)
        return len(observations)

    @staticmethod
    def _append_unique(target: list[str], value: str) -> None:
        if value and value not in target:
            target.append(value)
