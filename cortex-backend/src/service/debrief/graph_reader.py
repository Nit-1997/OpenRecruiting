"""DebriefGraphReader — all Cypher against the Cortex graph (spec §5 Graph rows,
§6.2/§6.5/§6.6). Returns typed dataclasses; no scoring logic here.

GRAPH CONVENTIONS (confirmed in recon — every query MUST honour these):
- Edges are `[:RELATES_TO {name: 'X'}]`, NOT typed edges. Filter on `r.name`
  (e.g. 'STRONG_IN', 'WEAK_IN', 'ASSESSED_ON', 'EXHIBITS', 'ASSESSES',
  'REQUIRES', 'DEMONSTRATED', 'CLAIMED', 'CONDUCTED', 'INTERVIEWED_IN').
- TENANT WALL: every node binding includes `n.group_id = $org_id`.
- TOMBSTONE: every edge includes `r.invalid_at IS NULL` (skip superseded
  extractions).
- First-class nodes are addressable by their `*_ref` top-level property
  (`candidate_ref`, `requisition`/`round`), NOT by recomputing uuid5 hashes.
- `polarity` is a property on the Trait NODE (`t.polarity`), not the edge.
- Corroboration key = a must-have concept node reached from ≥2 DISTINCT source
  rounds (`r._source_id`, candidate_round) — independent convergence across
  rounds (spec §6.5). The strict additional "≥2 distinct interviewers" AND-gate
  was dropped: interviewer provenance is sparse, and the spec's "independent
  convergence across rounds" IS satisfied by ≥2 distinct observing rounds.
- DEFENSE-IN-DEPTH: a post-read assertion drops/raises any row whose
  `group_id != org_id`.

SKELETON: signatures are PINNED; bodies are `NotImplementedError`. The implementer
writes the Cypher + post-read org guard and maps rows to the dataclasses below.
"""

import structlog

from src.config.database import Neo4jDriver
from src.model.debrief import CompetencyStanding, TraitObservation

logger = structlog.get_logger(__name__)


class OrgScopeViolation(RuntimeError):
    """Raised by the post-read defense-in-depth guard when a returned row carries a
    `group_id` other than the requested `org_id` — a cross-tenant leak that must
    never reach a packet (spec §14). The Cypher tenant wall should make this
    impossible; this is the second wall."""


# Competency-standing relations (Candidate -> Competency/Skill). The first three
# target Competency nodes, the last two target Skill nodes; both are concept nodes
# canonicalized per org so a single MATCH over `r.name` covers all five.
_STANDING_RELATIONS = ["STRONG_IN", "WEAK_IN", "ASSESSED_ON", "DEMONSTRATED", "CLAIMED"]


class DebriefGraphReader:
    """Org-scoped, tombstone-filtered reads of competency standings, trait
    observations, assessed/required dimensions and corroboration counts."""

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    # -- shared defense-in-depth guard (spec §14) --------------------------------
    @staticmethod
    def _guard_rows(rows: list[dict], org_id: str) -> list[dict]:
        """Drop/raise on any row whose selected-back `gid` (the node `group_id`)
        differs from `org_id`. A real mismatch is a tenant leak — log and raise."""
        for row in rows:
            gid = row.get("gid")
            if gid is not None and gid != org_id:
                logger.error("debrief_graph_org_leak", expected=org_id, got=gid)
                raise OrgScopeViolation(
                    f"row group_id {gid!r} != requested org_id {org_id!r}"
                )
        return rows

    async def fetch_dimensions(
        self,
        org_id: str,
        requisition_id: str,
    ) -> list[str]:
        """Return the role-anchored matrix dimensions: the deduped union of
        `Requisition-[REQUIRES]->Skill` and `Round-[ASSESSES]->Competency` for the
        requisition (canonical concept-node names). Order is finalized by the
        scorer; this returns the raw graph-sourced set."""
        # Two plain MATCHes UNION'd at top level (no CALL{} subquery — older Neo4j
        # here may not support it). `ord` keeps REQUIRES skills ahead of ASSESSES
        # competencies; the scorer finalizes the must-have ordering downstream.
        query = """
        MATCH (req:Requisition {requisition_ref: $req_id, group_id: $org_id})
              -[r:RELATES_TO]->(skill {group_id: $org_id})
        WHERE r.name = 'REQUIRES' AND r.invalid_at IS NULL
        RETURN skill.name AS dimension, skill.group_id AS gid, 0 AS ord
        UNION
        MATCH (req:Requisition {requisition_ref: $req_id, group_id: $org_id})
              -[hr:RELATES_TO]->(rnd:Round {group_id: $org_id})
        MATCH (rnd)-[r:RELATES_TO]->(comp {group_id: $org_id})
        WHERE hr.name = 'HAS_ROUND' AND hr.invalid_at IS NULL
          AND r.name = 'ASSESSES' AND r.invalid_at IS NULL
        RETURN comp.name AS dimension, comp.group_id AS gid, 1 AS ord
        """
        rows = await self._driver.execute_read(
            query, parameters={"org_id": org_id, "req_id": requisition_id}
        )
        self._guard_rows(rows, org_id)

        dimensions: list[str] = []
        seen: set[str] = set()
        for row in rows:
            name = row.get("dimension")
            if not name or name in seen:
                continue
            seen.add(name)
            dimensions.append(name)
        return dimensions

    async def fetch_competency_standings(
        self,
        org_id: str,
        candidate_ids: list[str],
    ) -> list[CompetencyStanding]:
        """Return each candidate's standing per dimension from
        `Candidate-[STRONG_IN|WEAK_IN|ASSESSED_ON]->Competency` and
        `Candidate-[DEMONSTRATED|CLAIMED]->Skill` (graph weight + standing label).
        One `CompetencyStanding` per (candidate, dimension) with any graph signal."""
        if not candidate_ids:
            return []

        # Relation literals are inlined (not parameterized) so the filtered set is
        # self-documenting and directly assertable in tests; `_STANDING_RELATIONS`
        # is the single source for both the Cypher list and any caller reference.
        relations_literal = ", ".join(f"'{rel}'" for rel in _STANDING_RELATIONS)
        query = f"""
        UNWIND $candidate_ids AS cid
        MATCH (c:Candidate {{candidate_ref: cid, group_id: $org_id}})
              -[r:RELATES_TO]->(concept {{group_id: $org_id}})
        WHERE r.name IN [{relations_literal}] AND r.invalid_at IS NULL
        RETURN cid AS candidate_id,
               concept.name AS dimension,
               r.name AS standing,
               r.evidence_status AS evidence_status,
               r.weight AS weight,
               concept.group_id AS gid
        """
        rows = await self._driver.execute_read(
            query,
            parameters={"org_id": org_id, "candidate_ids": candidate_ids},
        )
        self._guard_rows(rows, org_id)

        standings: list[CompetencyStanding] = []
        for row in rows:
            dimension = row.get("dimension")
            if not dimension:
                continue
            standings.append(
                CompetencyStanding(
                    candidate_id=row["candidate_id"],
                    dimension=dimension,
                    standing=row.get("standing"),
                    evidence_status=row.get("evidence_status"),
                    assessment_score=None,  # Supabase-sourced; never from the graph
                    weight=row.get("weight"),
                )
            )
        return standings

    async def fetch_trait_observations(
        self,
        org_id: str,
        candidate_ids: list[str],
    ) -> list[TraitObservation]:
        """Return every live `Candidate-[EXHIBITS]->Trait` observation for the set
        (trait name, node `polarity`, edge weight, `_source_id` round, conducting
        interviewer). Feeds §6.6 themes and §6.5 corroboration."""
        if not candidate_ids:
            return []

        query = """
        UNWIND $candidate_ids AS cid
        MATCH (c:Candidate {candidate_ref: cid, group_id: $org_id})
              -[r:RELATES_TO]->(t:Trait {group_id: $org_id})
        WHERE r.name = 'EXHIBITS' AND r.invalid_at IS NULL
        OPTIONAL MATCH (intv:Interviewer {group_id: $org_id})
              -[cond:RELATES_TO]->(rnd:Round {group_id: $org_id})
        WHERE cond.name = 'CONDUCTED' AND cond.invalid_at IS NULL
          AND cond._source_id = r._source_id
        RETURN cid AS candidate_id,
               t.name AS trait,
               t.polarity AS polarity,
               r.weight AS weight,
               r._source_id AS source_round_id,
               intv.name AS interviewer_name,
               t.group_id AS gid
        """
        rows = await self._driver.execute_read(
            query, parameters={"org_id": org_id, "candidate_ids": candidate_ids}
        )
        self._guard_rows(rows, org_id)

        observations: list[TraitObservation] = []
        for row in rows:
            trait = row.get("trait")
            if not trait:
                continue
            observations.append(
                TraitObservation(
                    candidate_id=row["candidate_id"],
                    trait=trait,
                    polarity=row.get("polarity"),
                    weight=row.get("weight"),
                    source_round_id=row.get("source_round_id"),
                    interviewer_name=row.get("interviewer_name"),
                )
            )
        return observations

    async def fetch_corroboration(
        self,
        org_id: str,
        candidate_ids: list[str],
        must_have_names: list[str],
    ) -> dict[str, int]:
        """Return per-candidate corroboration counts (§6.5), MUST-HAVE-SCOPED:
        the number of MUST-HAVE concept nodes a candidate reaches that show
        independent convergence across rounds — i.e. reached from ≥2 DISTINCT
        source rounds (`r._source_id`). Keyed by candidate_id.

        This is the §6.5 "corroboration on ≥ half the must-haves" input, so it
        counts ONLY concepts in `must_have_names` (apples-to-apples with the
        scorer's `ceil(num_must_have/2)` comparison). The strict additional "≥2
        distinct interviewers" AND-gate is intentionally NOT applied: interviewer
        provenance is sparse, and ≥2 distinct observing rounds IS the spec's
        "independent convergence across rounds". Org-scope + `r.invalid_at IS NULL`
        + the post-read org guard are kept."""
        # Must-have-scoped: with no must-have concepts there is nothing to
        # converge on — short-circuit to zeros without touching the driver.
        if not candidate_ids or not must_have_names:
            return {cid: 0 for cid in candidate_ids}

        query = """
        UNWIND $candidate_ids AS cid
        MATCH (c:Candidate {candidate_ref: cid, group_id: $org_id})
              -[r:RELATES_TO]->(concept {group_id: $org_id})
        WHERE r.invalid_at IS NULL AND r._source_id IS NOT NULL
          AND (concept:Competency OR concept:Skill OR concept:Trait)
          AND concept.name IN $must_have_names
        WITH cid,
             concept,
             c.group_id AS gid,
             count(DISTINCT r._source_id) AS source_count
        WITH cid,
             gid,
             sum(CASE WHEN source_count >= 2 THEN 1 ELSE 0 END) AS corroboration_count
        RETURN cid AS candidate_id, corroboration_count, gid
        """
        rows = await self._driver.execute_read(
            query,
            parameters={
                "org_id": org_id,
                "candidate_ids": candidate_ids,
                "must_have_names": must_have_names,
            },
        )
        self._guard_rows(rows, org_id)

        counts: dict[str, int] = {cid: 0 for cid in candidate_ids}
        for row in rows:
            cid = row.get("candidate_id")
            if cid is None:
                continue
            counts[cid] = int(row.get("corroboration_count") or 0)
        return counts
