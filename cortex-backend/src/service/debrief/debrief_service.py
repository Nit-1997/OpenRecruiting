"""DebriefService — orchestrates the debrief skill (spec §8). Pure orchestration:
no I/O logic inline; it only wires the injected single-responsibility components.

Pipeline:
    scaffold (Supabase) → graph reads (Neo4j) → scorer (build DebriefSpine)
    → theme builder → prose pass (LLM) → packet builder → DebriefPacket

REAL BODY: this calls only the PINNED interfaces. The called methods currently
`raise NotImplementedError`; once the implementers fill them, this orchestration
works unchanged.
"""

import uuid
from datetime import datetime, timezone

import structlog

from src.model.debrief import (
    CandidateSpine,
    CellScore,
    CompetencyStanding,
    DebriefPacket,
    DebriefPanelVote,
    DebriefSpine,
    Dimension,
    PanelMember,
    RoundRating,
)
from src.service.debrief.dimension_resolver import DimensionResolver
from src.service.debrief.graph_reader import DebriefGraphReader
from src.service.debrief.packet_builder import PacketBuilder
from src.service.debrief.prose_synthesizer import ProseSynthesizer
from src.service.debrief.scorer import DebriefScorer
from src.service.debrief.supabase_scaffold import SupabaseScaffold
from src.service.debrief.theme_builder import ThemeBuilder

logger = structlog.get_logger(__name__)

# Identity map: candidate_rounds.rating → DebriefVote (spec §6.6). Both literal
# sets are intentionally identical, so this is a pass-through validated against
# the allowed votes; unknown ratings drop the vote rather than corrupt the enum.
_VALID_VOTES = {"strong_yes", "yes", "maybe", "no", "strong_no"}


class DebriefService:
    """Stateless, idempotent: (org_id, requisition_id, candidate_ids) → DebriefPacket."""

    def __init__(
        self,
        scaffold: SupabaseScaffold,
        graph_reader: DebriefGraphReader,
        scorer: DebriefScorer,
        theme_builder: ThemeBuilder,
        prose_synthesizer: ProseSynthesizer,
        packet_builder: PacketBuilder,
        dimension_resolver: DimensionResolver | None = None,
    ) -> None:
        self._scaffold = scaffold
        self._graph = graph_reader
        self._scorer = scorer
        self._themes = theme_builder
        self._prose = prose_synthesizer
        self._packets = packet_builder
        # Pure/stateless; default-constructed unless injected (e.g. for tests).
        self._dimensions = dimension_resolver or DimensionResolver()

    async def generate(
        self,
        org_id: str,
        requisition_id: str,
        candidate_ids: list[str],
    ) -> DebriefPacket:
        """Assemble a complete comparative `DebriefPacket` for the candidate set."""
        logger.info(
            "debrief_generate_start",
            org_id=org_id,
            requisition_id=requisition_id,
            candidate_count=len(candidate_ids),
        )

        # 1. Supabase ground-truth scaffold.
        scaffold = await self._scaffold.build(org_id, requisition_id, candidate_ids)

        # 2. Graph value-add reads (all org-scoped + tombstone-filtered downstream).
        graph_dimensions = await self._graph.fetch_dimensions(org_id, requisition_id)
        standings = await self._graph.fetch_competency_standings(org_id, candidate_ids)
        trait_observations = await self._graph.fetch_trait_observations(org_id, candidate_ids)

        # 3. Resolve the ordered, tiered matrix dimensions across THREE sources
        #    (addendum §3): Supabase skills + feedback headings ∪ graph REQUIRES/
        #    ASSESSES. Non-empty whenever any skill or feedback heading exists, so a
        #    bare graph no longer yields an empty packet. Corroboration (§6.5) is
        #    MUST-HAVE-SCOPED, so resolve before the corroboration read.
        resolved = self._dimensions.resolve(scaffold, graph_dimensions)
        dimensions = [d.name for d in resolved]
        must_have_dims = {d.name for d in resolved if d.tier == "must_have"}
        corroboration = await self._graph.fetch_corroboration(
            org_id, candidate_ids, sorted(must_have_dims)
        )
        # Index graph standings by (candidate, canonical_key) so a graph standing
        # matches its dimension regardless of casing/whitespace differences.
        standings_index = self._index_standings(standings)

        candidate_spines: list[CandidateSpine] = []
        for candidate_id in candidate_ids:
            candidate_spines.append(
                self._build_candidate_spine(
                    candidate_id=candidate_id,
                    scaffold=scaffold,
                    resolved_dimensions=resolved,
                    must_have_dims=must_have_dims,
                    standings_index=standings_index,
                    trait_observations=trait_observations,
                    corroboration=corroboration,
                )
            )

        # 4. Rank across candidates (pre-sorts so index 0 is the recommendation).
        candidate_spines = self._scorer.rank(candidate_spines)

        # 5. Cross-candidate themes + per-candidate strengths/concerns.
        themes = self._themes.build_themes(trait_observations)
        for spine in candidate_spines:
            strengths, concerns = self._themes.strengths_and_concerns(spine)
            spine.top_strengths = strengths
            spine.top_concerns = concerns

        # 5b. Enrichment tier (addendum §2/§5): cortex_density = (#cells Cortex
        #     contributed to) + (#themes) + (#corroborations). >0 → graph_enriched.
        #     Drives BOTH the matrix shape (PacketBuilder) and the risk scope below.
        cortex_density = self._cortex_density(candidate_spines, themes, corroboration)
        enrichment_tier = "graph_enriched" if cortex_density > 0 else "baseline"

        # 5c. Risk seeds. In the baseline tier the rendered matrix is round-based
        #     (no competency cells shown), so suppress "no evidence for must-have"
        #     noise and surface only contradictions; the enriched tier keeps gaps.
        risk_must_haves = must_have_dims if enrichment_tier == "graph_enriched" else set()
        risks = self._themes.risks_and_gaps(candidate_spines, risk_must_haves)

        # 6. Assemble the full deterministic spine.
        debrief_spine = DebriefSpine(
            org_id=org_id,
            requisition_id=requisition_id,
            role_title=scaffold.role_title,
            dimensions=dimensions,
            must_have_dimensions=must_have_dims,
            candidates=candidate_spines,
            panel_members=self._build_panel_members(scaffold),
            themes=themes,
            source_stats=self._build_source_stats(scaffold),
            confidence=self._overall_confidence(
                candidate_spines, scaffold, must_have_dims, corroboration
            ),
            overall_verdict=candidate_spines[0].verdict if candidate_spines else "mixed",
            risks=risks,
            enrichment_tier=enrichment_tier,
            cortex_density=cortex_density,
        )

        # 7. Single bounded LLM prose pass (fail-soft inside the synthesizer).
        prose = await self._prose.synthesize(debrief_spine)

        # 8. Deterministic packet assembly (enum validity, ranking, em-dash cells).
        packet = self._packets.build(
            spine=debrief_spine,
            prose=prose,
            packet_id=str(uuid.uuid4()),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(
            "debrief_generate_complete",
            org_id=org_id,
            requisition_id=requisition_id,
            verdict=packet.verdict,
            confidence=packet.confidence,
        )
        return packet

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _canonical_key(name: str) -> str:
        """`casefold(collapse_whitespace(trim(name)))` — the shared cross-source
        match key (addendum §3). Identical to DimensionResolver's key."""
        return " ".join((name or "").strip().split()).casefold()

    def _index_standings(
        self,
        standings: list[CompetencyStanding],
    ) -> dict[tuple[str, str], CompetencyStanding]:
        """(candidate_id, canonical_key) → graph standing, for O(1) canonical-match
        cell lookup (so 'Pricing' matches a 'pricing' standing)."""
        return {(s.candidate_id, self._canonical_key(s.dimension)): s for s in standings}

    def _scores_by_canonical(self, raw: dict[str, float]) -> dict[str, float]:
        """Re-key a {category -> assessment score} map by canonical key so an
        assessment category matches the resolved dimension regardless of casing."""
        return {self._canonical_key(name): value for name, value in raw.items()}

    def _status_by_canonical(self, raw: dict[str, str]) -> dict[str, str]:
        """Re-key a {heading -> evidence_status} map by canonical key so a feedback
        heading matches the resolved dimension regardless of casing/whitespace."""
        return {self._canonical_key(name): value for name, value in raw.items()}

    def _build_candidate_spine(
        self,
        candidate_id: str,
        scaffold,
        resolved_dimensions: list[Dimension],
        must_have_dims: set[str],
        standings_index: dict[tuple[str, str], CompetencyStanding],
        trait_observations: list,
        corroboration: dict[str, int],
    ) -> CandidateSpine:
        """Score every dimension cell for one candidate (addendum §4 — Cortex leads,
        Supabase grounds) and roll up aggregate/verdict/confidence. A candidate with
        ZERO scorable cells gets a verdict from the panel rating (addendum §5), never
        a forced no_hire. Rank is filled later by the scorer."""
        # Re-key Supabase maps by canonical key so they match the resolved
        # dimensions regardless of casing/whitespace differences.
        assessment_by_key = self._scores_by_canonical(
            scaffold.assessment_scores.get(candidate_id, {})
        )
        evidence_by_key = self._status_by_canonical(
            scaffold.evidence_status.get(candidate_id, {})
        )

        cells: list[CellScore] = []
        cortex_cell_count = 0
        for dim in resolved_dimensions:
            key = dim.canonical_key
            is_must_have = dim.tier == "must_have"
            assessment_score = assessment_by_key.get(key)
            graph_standing = standings_index.get((candidate_id, key))
            supabase_status = evidence_by_key.get(key)

            # Cortex lead = the graph standing LABEL; Supabase grounding = the
            # Supabase evidence_status (graph edge status is NOT consulted for
            # scoring). Build one CompetencyStanding carrying both for the scorer.
            standing = self._lead_standing(
                candidate_id, dim.name, graph_standing, supabase_status
            )
            if graph_standing is not None and graph_standing.standing is not None:
                cortex_cell_count += 1

            cell = self._scorer.score_cell(
                standing=standing,
                assessment_score=assessment_score,
                is_must_have=is_must_have,
            )
            # The scorer copies identity from `standing`; on a status/assessment-only
            # cell there is none, so stamp the (candidate, display-name dimension)
            # the orchestrator owns, keyed to the resolved display name.
            cell.candidate_id = candidate_id
            cell.dimension = dim.name
            cells.append(cell)

        candidate_traits = [t for t in trait_observations if t.candidate_id == candidate_id]
        contradiction_count = sum(1 for c in cells if c.contradicted)
        must_have_cells = [c for c in cells if c.is_must_have]
        covered_must_have = sum(1 for c in must_have_cells if c.value is not None)
        coverage_pct = (covered_must_have / len(must_have_cells) * 100.0) if must_have_cells else 0.0

        # Rating spine (2026-06-08 §2): the comparative score IS the per-round
        # `candidate_rounds.rating` averaged across the candidate's rated rounds and
        # rescaled to the FE 1..4 contract. The competency cells above are kept for
        # the enriched matrix + risks/themes + confidence corroboration, not the score.
        ratings = [f.rating for f in scaffold.round_facts if f.candidate_id == candidate_id]
        rating_avg = self._scorer.rating_average(ratings)

        spine = CandidateSpine(
            candidate_id=candidate_id,
            name=scaffold.candidate_names.get(candidate_id, candidate_id),
            rounds_completed=self._completed_rounds(scaffold, candidate_id),
            rounds_total=scaffold.rounds_total_by_candidate.get(candidate_id, 0),
            cells=cells,
            round_ratings=self._build_round_ratings(scaffold, candidate_id),
            must_have_coverage_pct=coverage_pct,
            corroboration_count=corroboration.get(candidate_id, 0),
            contradiction_count=contradiction_count,
            panel_votes=self._build_panel_votes(scaffold, candidate_id),
            trait_observations=candidate_traits,
            # Insufficient = NO rated round at all (eligibility should exclude this);
            # the 0.0 aggregate is then an honest sentinel, not a real /4.
            aggregate_insufficient=rating_avg is None,
            cortex_cell_count=cortex_cell_count,
        )
        spine.aggregate_score = (
            self._scorer.rescale_to_four(rating_avg) if rating_avg is not None else 0.0
        )
        spine.verdict = self._scorer.verdict_from_average(rating_avg)
        return spine

    def _build_round_ratings(self, scaffold, candidate_id: str) -> list[RoundRating]:
        """Per rated completed round → a normalized 1..4 `RoundRating` for the
        baseline round-decision matrix (§3). Rounds without a usable rating are
        skipped (not scorable)."""
        out: list[RoundRating] = []
        for fact in scaffold.round_facts:
            if fact.candidate_id != candidate_id:
                continue
            points = self._scorer.rating_points(fact.rating)
            if points is None:
                continue
            out.append(
                RoundRating(
                    round_id=fact.round_id,
                    round_name=fact.round_name,
                    value=self._scorer.rescale_to_four(float(points)),
                )
            )
        return out

    @staticmethod
    def _lead_standing(
        candidate_id: str,
        dimension: str,
        graph_standing: CompetencyStanding | None,
        supabase_status: str | None,
    ) -> CompetencyStanding | None:
        """Build the `CompetencyStanding` handed to the scorer (addendum §4). The
        Cortex graph standing's LABEL leads; the Supabase evidence_status grounds.
        Returns None when there is neither a graph standing nor a Supabase status.

        - Graph standing present → reuse its label, OVERRIDE its evidence_status
          with the Supabase grounding status (Supabase grounds, always).
        - No graph standing but a Supabase status → a label-less standing carrying
          the status (scorer derives a Supabase-only base).
        - Neither → None.
        """
        if graph_standing is not None:
            return CompetencyStanding(
                candidate_id=graph_standing.candidate_id,
                dimension=graph_standing.dimension,
                standing=graph_standing.standing,
                evidence_status=supabase_status,  # Supabase grounds, not the edge.
                assessment_score=graph_standing.assessment_score,
                weight=graph_standing.weight,
            )
        if supabase_status is not None:
            return CompetencyStanding(
                candidate_id=candidate_id,
                dimension=dimension,
                standing=None,
                evidence_status=supabase_status,
                assessment_score=None,
                weight=None,
            )
        return None

    @staticmethod
    def _cortex_density(
        candidates: list[CandidateSpine],
        themes: list,
        corroboration: dict[str, int],
    ) -> int:
        """Addendum §2/§5: (#cells Cortex contributed to) + (#themes) +
        (#corroborations). Drives the enrichment tier."""
        cortex_cells = sum(c.cortex_cell_count for c in candidates)
        corroborations = sum(corroboration.values())
        return cortex_cells + len(themes) + corroborations

    @staticmethod
    def _completed_rounds(scaffold, candidate_id: str) -> int:
        return sum(
            1
            for fact in scaffold.round_facts
            if fact.candidate_id == candidate_id and fact.has_feedback
        )

    def _build_panel_votes(self, scaffold, candidate_id: str) -> list[DebriefPanelVote]:
        """§6.6: one vote per completed round for the candidate. Drops rounds with
        an unknown/absent rating so the enum stays valid (FE renders em-dash)."""
        votes: list[DebriefPanelVote] = []
        for fact in scaffold.round_facts:
            if fact.candidate_id != candidate_id:
                continue
            if fact.rating not in _VALID_VOTES:
                continue
            panelist = fact.interviewer_name or fact.interviewer_email or "Interviewer"
            rationale = (fact.summary or "").strip()[:140] or None
            votes.append(
                DebriefPanelVote(
                    panelist=panelist,
                    panelist_role=fact.round_name or fact.round_category or "Interview",
                    vote=fact.rating,  # validated against _VALID_VOTES above
                    rationale=rationale,
                )
            )
        return votes

    @staticmethod
    def _build_panel_members(scaffold) -> list[PanelMember]:
        """Union of distinct round interviewers across the set. `initials`/`color`
        are finalized by `PacketBuilder`; here we only need the names/roles, so a
        minimal placeholder is filled and PacketBuilder re-derives presentation."""
        seen: set[str] = set()
        members: list[PanelMember] = []
        for fact in scaffold.round_facts:
            name = fact.interviewer_name or fact.interviewer_email
            if not name or name in seen:
                continue
            seen.add(name)
            members.append(
                PanelMember(
                    name=name,
                    role=fact.round_name or fact.round_category or "Interviewer",
                    initials="",
                    color="",
                )
            )
        return members

    @staticmethod
    def _build_source_stats(scaffold):
        from src.model.debrief import DebriefSourceStats

        return DebriefSourceStats(
            scorecards=scaffold.scorecard_count,
            transcripts=scaffold.transcript_count,
        )

    def _overall_confidence(
        self, candidates: list[CandidateSpine], scaffold, must_have_dims: set[str], corroboration: dict[str, int]
    ) -> str:
        """Overall packet confidence = the top-ranked candidate's rating-based
        confidence (2026-06-08 §4): rating volume + panel disagreement, plus Cortex
        corroboration when must-haves exist. Falls back to 'low' on an empty set."""
        if not candidates:
            return "low"
        top = candidates[0]
        ratings = [f.rating for f in scaffold.round_facts if f.candidate_id == top.candidate_id]
        return self._scorer.confidence_from_ratings(
            ratings, corroboration.get(top.candidate_id, 0), len(must_have_dims)
        )
