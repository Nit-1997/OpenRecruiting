"""PacketBuilder — assembles the final `DebriefPacket` (spec §4) from the
deterministic spine + the §7 `ProseBundle`. PURE: zero I/O.

Enforces the render invariants:
- `candidates` pre-ranked (index 0 = winner) — the spine is already ranked, so
  order is preserved verbatim (never re-sorted here).
- `decision_matrix[].scores` OMITS a candidate key when its cell is `None`
  (renders an em-dash); never emit 0 for "no evidence".
- `winner_ids` = candidate(s) with the max present score in the row (ties kept).
- `panel_votes[].panelist` string-matched to `panel_members[].name`.
- `initials`/`color` derived deterministically from the candidate/panelist name.
- enum validity guarded against the §4 literal sets BEFORE construction (clear
  error on a bad spine value); Pydantic is the backstop on construction.
- `score_scale == 4` on every candidate.
"""

import hashlib

import structlog

from src.model.debrief import (
    CandidateSpine,
    DebriefCandidateSnapshot,
    DebriefDecisionRow,
    DebriefPacket,
    DebriefSpine,
    DebriefStatus,
    DebriefTheme,
    PanelMember,
    ProseBundle,
)

logger = structlog.get_logger(__name__)

# §4 literal sets — kept here as runtime-checkable frozensets so the builder can
# fail with a readable error before Pydantic raises a deep ValidationError. These
# MUST mirror the `Literal[...]` unions in `model/debrief.py` / the FE TS types.
_VALID_VERDICTS: frozenset[str] = frozenset({"strong_hire", "hire", "mixed", "no_hire"})
_VALID_VOTES: frozenset[str] = frozenset({"strong_yes", "yes", "maybe", "no", "strong_no"})
_VALID_TONES: frozenset[str] = frozenset({"pos", "neg", "neu"})
_VALID_CONFIDENCE: frozenset[str] = frozenset({"low", "medium", "high"})
_VALID_STATUS: frozenset[str] = frozenset({"fresh", "superseded"})

_STATUS_FRESH: DebriefStatus = "fresh"
_GENERATED_BY = "Scout debrief agent"
_SCORE_SCALE = 4

# Curated, readable avatar-background palette. A name maps to a stable slot via a
# salted-hash modulo so the same name ALWAYS lands on the same color across
# processes (Python's builtin hash() is salted per-run and unusable for this).
_AVATAR_PALETTE: tuple[str, ...] = (
    "#2563eb",  # blue
    "#16a34a",  # green
    "#dc2626",  # red
    "#d97706",  # amber
    "#7c3aed",  # violet
    "#0891b2",  # cyan
    "#db2777",  # pink
    "#4f46e5",  # indigo
    "#ca8a04",  # gold
    "#059669",  # emerald
    "#e11d48",  # rose
    "#0d9488",  # teal
)


class PacketBuilder:
    """Deterministic assembly of the FE-contract `DebriefPacket` from spine + prose."""

    def build(
        self,
        spine: DebriefSpine,
        prose: ProseBundle,
        packet_id: str,
        generated_at: str,
    ) -> DebriefPacket:
        """Assemble the complete `DebriefPacket`. `packet_id` and `generated_at`
        (ISO) are supplied by the orchestrator so this stays pure/deterministic.
        Status is always 'fresh' at build time. Raises a clear `ValueError` if the
        spine handed an enum value outside the §4 literal sets (defensive)."""
        self._validate_enums(spine)

        candidates = [self._snapshot(c, prose) for c in spine.candidates]
        decision_matrix = self._build_matrix(spine, prose)
        themes = self._build_themes(spine.themes, prose)
        panel_members = [self._finalize_member(m) for m in spine.panel_members]

        packet = DebriefPacket(
            id=packet_id,
            requisition_id=spine.requisition_id,
            role_title=spine.role_title,
            title=self._title(spine),
            subtitle=self._subtitle(spine),
            generated_at=generated_at,
            generated_by=_GENERATED_BY,
            status=_STATUS_FRESH,
            confidence=spine.confidence,  # validated above
            verdict=spine.overall_verdict,  # validated above
            headline_recommendation=prose.headline_recommendation,
            panel_members=panel_members,
            candidates=candidates,
            source_stats=spine.source_stats,
            themes=themes,
            decision_matrix=decision_matrix,
            risks=list(prose.risks),
            next_steps=list(prose.next_steps),
        )
        return packet

    # ------------------------------------------------------------------ candidates
    def _snapshot(self, candidate: CandidateSpine, prose: ProseBundle) -> DebriefCandidateSnapshot:
        """Map ONE pre-ranked `CandidateSpine` → `DebriefCandidateSnapshot`. Prose
        fields come from `prose.per_candidate[id]` (empty-string fallback); the rest
        is deterministic. `score_scale` is ALWAYS 4."""
        candidate_prose = prose.per_candidate.get(candidate.candidate_id, {})
        return DebriefCandidateSnapshot(
            candidate_id=candidate.candidate_id,
            name=candidate.name,
            initials=self._initials(candidate.name),
            color=self._color(candidate.name),
            rank=candidate.rank,
            verdict=candidate.verdict,  # validated
            headline=candidate_prose.get("headline", ""),
            aggregate_score=candidate.aggregate_score,
            score_scale=_SCORE_SCALE,
            rounds_completed=candidate.rounds_completed,
            rounds_total=candidate.rounds_total,
            top_strengths=list(candidate.top_strengths),
            top_concerns=list(candidate.top_concerns),
            recommendation=candidate_prose.get("recommendation", ""),
            panel_votes=list(candidate.panel_votes),  # already validated + name-joined
            aggregate_insufficient=candidate.aggregate_insufficient,  # addendum §5
        )

    # ------------------------------------------------------------------ matrix
    def _build_matrix(self, spine: DebriefSpine, prose: ProseBundle) -> list[DebriefDecisionRow]:
        """The comparison grid. In the GRAPH-ENRICHED tier it's the competency
        matrix (one row per `spine.dimensions`); in the BASELINE tier it's the
        round-decision matrix (one row per round, cells = the candidate's
        normalized `candidate_rounds.rating`) — the differentiating view when there
        is no Cortex signal (spec 2026-06-08 §3)."""
        if spine.enrichment_tier == "graph_enriched":
            return self._competency_matrix(spine, prose)
        return self._round_matrix(spine, prose)

    def _competency_matrix(self, spine: DebriefSpine, prose: ProseBundle) -> list[DebriefDecisionRow]:
        """One row per `spine.dimensions`. A `None` cell OMITS that candidate's key
        (em-dash, never 0). `winner_ids` = max present score (ties kept)."""
        rows: list[DebriefDecisionRow] = []
        for dimension in spine.dimensions:
            scores: dict[str, float] = {}
            for candidate in spine.candidates:
                cell = self._cell_for(candidate, dimension)
                if cell is not None and cell.value is not None:
                    scores[candidate.candidate_id] = cell.value
            rows.append(
                DebriefDecisionRow(
                    dimension=dimension,
                    scores=scores,
                    winner_ids=self._winner_ids(scores),
                    note=prose.matrix_notes.get(dimension, ""),
                )
            )
        return rows

    def _round_matrix(self, spine: DebriefSpine, prose: ProseBundle) -> list[DebriefDecisionRow]:
        """One row per round (the baseline tier). Rounds are the ordered union of
        every candidate's rated rounds, keyed by `round_id` (so the same round
        aligns across candidates) and labelled by `round_name`. A candidate missing
        a round is OMITTED from that row (em-dash). Display labels are made unique
        so two distinct rounds never collide on the FE row key."""
        ordered: list[tuple[str, str]] = []  # (round_id, round_name), first-seen order
        seen_round_ids: set[str] = set()
        for candidate in spine.candidates:
            for rr in candidate.round_ratings:
                if rr.round_id not in seen_round_ids:
                    seen_round_ids.add(rr.round_id)
                    ordered.append((rr.round_id, rr.round_name))

        rows: list[DebriefDecisionRow] = []
        used_labels: dict[str, int] = {}
        for round_id, round_name in ordered:
            scores: dict[str, float] = {}
            for candidate in spine.candidates:
                value = next(
                    (rr.value for rr in candidate.round_ratings if rr.round_id == round_id),
                    None,
                )
                if value is not None:
                    scores[candidate.candidate_id] = value
            label = self._unique_label(round_name or "Round", used_labels)
            rows.append(
                DebriefDecisionRow(
                    dimension=label,
                    scores=scores,
                    winner_ids=self._winner_ids(scores),
                    note=prose.matrix_notes.get(label, ""),
                )
            )
        return rows

    @staticmethod
    def _unique_label(label: str, used: dict[str, int]) -> str:
        """De-collide duplicate round display names so each matrix row has a
        distinct `dimension` (the FE row key). First use keeps the bare name."""
        count = used.get(label, 0)
        used[label] = count + 1
        return label if count == 0 else f"{label} ({count + 1})"

    @staticmethod
    def _cell_for(candidate: CandidateSpine, dimension: str):
        for cell in candidate.cells:
            if cell.dimension == dimension:
                return cell
        return None

    @staticmethod
    def _winner_ids(scores: dict[str, float]) -> list[str]:
        """candidate_id(s) holding the max present score; empty when no scores.
        Ties are all returned. Order follows the dict insertion order (candidate
        order) for stable output."""
        if not scores:
            return []
        top = max(scores.values())
        return [cid for cid, value in scores.items() if value == top]

    # ------------------------------------------------------------------ themes
    def _build_themes(self, themes: list[DebriefTheme], prose: ProseBundle) -> list[DebriefTheme]:
        """Apply `prose.theme_labels[index]` to override the label where present;
        keep tone/weight/evidence_count from the spine themes (order preserved)."""
        out: list[DebriefTheme] = []
        for index, theme in enumerate(themes):
            label = prose.theme_labels.get(index, theme.label)
            out.append(
                DebriefTheme(
                    label=label,
                    tone=theme.tone,  # validated
                    weight=theme.weight,
                    evidence_count=theme.evidence_count,
                )
            )
        return out

    # ------------------------------------------------------------------ panel
    def _finalize_member(self, member: PanelMember) -> PanelMember:
        """Re-derive presentation (initials/color) for a panel member from its name
        (the service leaves them blank). `name` is the join key for panel votes."""
        return PanelMember(
            name=member.name,
            role=member.role,
            initials=self._initials(member.name),
            color=self._color(member.name),
        )

    # ------------------------------------------------------------------ presentation
    @staticmethod
    def _initials(name: str) -> str:
        """1–2 uppercase letters: first letter of the first two words for a
        multi-word name; first two letters of a single word; '?' when empty."""
        words = [w for w in (name or "").split() if w]
        if not words:
            return "?"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][0] + words[1][0]).upper()

    @staticmethod
    def _color(name: str) -> str:
        """Deterministic, stable avatar hex from the name. Uses md5 (not builtin
        hash(), which is per-process salted) modulo the curated palette so the same
        name always renders the same color."""
        key = (name or "").strip().lower()
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()
        slot = int(digest, 16) % len(_AVATAR_PALETTE)
        return _AVATAR_PALETTE[slot]

    # ------------------------------------------------------------------ top-level
    @staticmethod
    def _title(spine: DebriefSpine) -> str:
        return f"{spine.role_title} Debrief"

    @staticmethod
    def _subtitle(spine: DebriefSpine) -> str:
        """Addendum §2: prefix the enrichment tier so the FE surfaces it with NO
        contract change (e.g. "Graph-enriched · 3 candidates compared")."""
        count = len(spine.candidates)
        noun = "candidate" if count == 1 else "candidates"
        tier_label = "Graph-enriched" if spine.enrichment_tier == "graph_enriched" else "Baseline"
        return f"{tier_label} · {count} {noun} compared"

    # ------------------------------------------------------------------ enum guard
    def _validate_enums(self, spine: DebriefSpine) -> None:
        """Fail loud with a readable message if the spine carries any enum value
        outside the §4 literal sets — a programming/upstream error, not data. This
        runs BEFORE Pydantic so the error names the exact offending value."""
        self._require(spine.overall_verdict, _VALID_VERDICTS, "overall verdict")
        self._require(spine.confidence, _VALID_CONFIDENCE, "confidence")

        for candidate in spine.candidates:
            self._require(
                candidate.verdict,
                _VALID_VERDICTS,
                f"verdict for candidate {candidate.candidate_id}",
            )
            for vote in candidate.panel_votes:
                self._require(
                    vote.vote,
                    _VALID_VOTES,
                    f"panel vote for candidate {candidate.candidate_id}",
                )

        for index, theme in enumerate(spine.themes):
            self._require(theme.tone, _VALID_TONES, f"theme tone at index {index}")

    @staticmethod
    def _require(value: object, allowed: frozenset[str], label: str) -> None:
        if value not in allowed:
            raise ValueError(
                f"Invalid {label}: {value!r} is not one of {sorted(allowed)}"
            )
