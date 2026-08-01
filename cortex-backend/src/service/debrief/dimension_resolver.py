"""DimensionResolver — tiered, deduped matrix-dimension resolution (addendum §3).

Replaces the graph-only `fetch_dimensions` mapping. Unions dimensions from THREE
sources and tiers them so the matrix is NON-EMPTY whenever any configured skill or
feedback heading exists — the fix for the live run that produced an empty packet
because the graph had no edges:

  1. Supabase `requisition.must_have_skills`   → tier `must_have`
     Supabase `requisition.good_to_have_skills`→ tier `nice_to_have`
  2. Supabase distinct `feedback_question.heading` across the selected candidates'
     completed rounds → tier `assessed`
  3. Graph `Requisition-[REQUIRES]->Skill`   → tier `must_have`
     Graph `Round-[ASSESSES]->Competency`    → tier `assessed`

Normalization + dedup: `canonical_key = casefold(collapse_whitespace(trim(name)))`.
On a canonical-key collision the HIGHEST tier wins (`must_have > nice_to_have >
assessed`) and the FIRST-seen display name is kept — sources are visited in tier
order so a configured skill's casing is preferred over a lowercased heading.

Ordering: `must_have` → `nice_to_have` → `assessed`; capped at 12 rows. (Within a
tier, source order is preserved; the §6.1 most-disagreement re-ordering stays a
scorer concern and is applied downstream against the resolved set.)

PURE: zero I/O. The graph reader supplies `graph_dimensions`/`graph_required`; the
scaffold supplies the Supabase seeds + feedback headings.
"""

from src.model.debrief import Dimension, DimensionTier, ScaffoldData

# Tier ranking for collision resolution + ordering (higher rank wins / sorts first).
_TIER_RANK: dict[str, int] = {"must_have": 3, "nice_to_have": 2, "assessed": 1}

_MAX_DIMENSIONS = 12


class DimensionResolver:
    """Union + dedup + tier + order the matrix dimensions across Supabase + graph.

    Stateless and pure — `resolve` is a function of its arguments."""

    def resolve(
        self,
        scaffold: ScaffoldData,
        graph_dimensions: list[str],
        graph_required: list[str] | None = None,
    ) -> list[Dimension]:
        """Return the ordered, tiered, deduped `list[Dimension]` (addendum §3).

        `graph_dimensions` = graph `ASSESSES` concepts (→ `assessed`).
        `graph_required`   = graph `REQUIRES` skills (→ `must_have`); optional
                             because the current `fetch_dimensions` returns only a
                             merged name list — callers that can distinguish the two
                             pass `graph_required` explicitly.
        """
        # Visit sources in tier-precedence order; the first time a canonical key is
        # seen fixes both its display name and (because of the order) its highest
        # eligible tier. Later, lower-tier sightings only upgrade-protect, never
        # downgrade — so a single forward pass with "first writer wins" is correct.
        ordered_sources: list[tuple[list[str], DimensionTier]] = [
            (scaffold.must_have_skills, "must_have"),
            (graph_required or [], "must_have"),
            (scaffold.nice_to_have_skills, "nice_to_have"),
            (scaffold.feedback_headings, "assessed"),
            (graph_dimensions, "assessed"),
        ]

        by_key: dict[str, Dimension] = {}
        for names, tier in ordered_sources:
            for raw_name in names:
                name = (raw_name or "").strip()
                if not name:
                    continue
                key = self._canonical_key(name)
                existing = by_key.get(key)
                if existing is None:
                    by_key[key] = Dimension(name=name, tier=tier, canonical_key=key)
                elif _TIER_RANK[tier] > _TIER_RANK[existing.tier]:
                    # A later source carries a HIGHER tier for the same concept —
                    # upgrade the tier but keep the first-seen display name.
                    existing.tier = tier

        dimensions = sorted(
            by_key.values(),
            key=lambda d: -_TIER_RANK[d.tier],  # stable: must_have → nice → assessed
        )
        return dimensions[:_MAX_DIMENSIONS]

    @staticmethod
    def _canonical_key(name: str) -> str:
        """`casefold(collapse_whitespace(trim(name)))` (addendum §3)."""
        return " ".join(name.strip().split()).casefold()
