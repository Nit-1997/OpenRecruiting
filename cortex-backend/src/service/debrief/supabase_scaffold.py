"""SupabaseScaffold — wraps `SupabaseFetcher` to assemble the ground-truth
`ScaffoldData` (spec §5 Supabase columns, §6.6 panel/source stats).

Each packet field that §5 sources from Supabase is read here and only here. The
graph reader (`DebriefGraphReader`) and scorer (`DebriefScorer`) consume the typed
`ScaffoldData` this produces — they never touch Supabase directly.

Sparse data is tolerated (spec D6): a candidate with no rounds / no feedback / no
assessments simply does not appear in `round_facts` and gets empty per-candidate
maps. This method never raises on partial data.
"""

import structlog

from src.model.debrief import CandidateRoundFact, ScaffoldData
from src.service.supabase_fetcher import SupabaseFetcher

logger = structlog.get_logger(__name__)

# candidate_rounds.rating values that map 1:1 to a DebriefVote (addendum §5).
_VALID_RATINGS = {"strong_yes", "yes", "maybe", "no", "strong_no"}


class SupabaseScaffold:
    """Reads requisition identity, must/nice-to-have dimension seeds, per-candidate
    completed round facts, the interviewer panel, assessment scores, evidence
    status and scorecard/transcript counts from Supabase into one `ScaffoldData`."""

    def __init__(self, fetcher: SupabaseFetcher) -> None:
        self._fetcher = fetcher

    async def build(
        self,
        org_id: str,
        requisition_id: str,
        candidate_ids: list[str],
    ) -> ScaffoldData:
        """Assemble the Supabase ground-truth scaffold for the candidate set.

        Tolerates sparse data (missing rounds/feedback/assessments) — never raises
        on partial data; absent signals simply do not appear in `ScaffoldData`.
        """
        plan = await self._fetcher.fetch_plan_packet(requisition_id)
        rounds_total = len(plan.rounds)

        names = await self._fetcher.fetch_candidate_names(candidate_ids)
        candidate_names = {
            cid: names.get(cid) or f"Candidate {cid[:8]}" for cid in candidate_ids
        }

        cr_rows = await self._fetcher.fetch_candidate_rounds_for_requisition(
            requisition_id, candidate_ids
        )
        candidate_round_ids = [row["id"] for row in cr_rows]

        # candidate_feedback presence (per round) AND per-dimension evidence_status.
        evidence_rows = await self._fetcher.fetch_evidence_status_by_dimension(
            candidate_round_ids
        )
        rounds_with_feedback = {row["candidate_round_id"] for row in evidence_rows}

        transcript_round_ids = set(
            await self._fetcher.fetch_transcript_round_ids(candidate_round_ids)
        )

        cr_to_candidate: dict[str, str] = {}
        round_facts: list[CandidateRoundFact] = []
        # Most-recent completed-round rating per candidate (addendum §5 verdict
        # fallback). `cr_rows` arrives in the fetcher's order; the last valid rating
        # for a candidate wins, so a later round overrides an earlier one.
        latest_rating_by_candidate: dict[str, str] = {}
        for row in cr_rows:
            cr_id = row["id"]
            candidate_id = row["candidate_id"]
            cr_to_candidate[cr_id] = candidate_id
            rating = row.get("rating")
            if rating in _VALID_RATINGS:
                latest_rating_by_candidate[candidate_id] = rating
            round = row.get("rounds") or {}
            round_facts.append(
                CandidateRoundFact(
                    candidate_round_id=cr_id,
                    candidate_id=candidate_id,
                    round_id=row["round_id"],
                    round_name=round.get("name") or "Round",
                    round_category=round.get("category"),
                    rating=row.get("rating"),
                    summary=row.get("summary"),
                    interviewer_email=row.get("interviewer_email"),
                    interviewer_name=row.get("interviewer_name"),
                    has_feedback=cr_id in rounds_with_feedback,
                    has_transcript=cr_id in transcript_round_ids,
                )
            )

        # candidate_id -> {dimension -> evidence_status} (strongest per dimension)
        # AND the distinct, trimmed feedback-heading set (addendum §3 source 2).
        # Both derive from the same per-heading evidence rows — the dimension key
        # is the TRIMMED heading so it matches DimensionResolver's display names.
        evidence_status: dict[str, dict[str, str]] = {}
        feedback_headings: list[str] = []
        seen_headings: set[str] = set()
        for row in evidence_rows:
            cid = cr_to_candidate.get(row["candidate_round_id"])
            raw_heading = (row.get("feedback_questions") or {}).get("heading")
            heading = (raw_heading or "").strip()
            status = row.get("evidence_status")
            if not cid or not heading or not status:
                continue
            if heading not in seen_headings:
                seen_headings.add(heading)
                feedback_headings.append(heading)
            dim_map = evidence_status.setdefault(cid, {})
            if self._stronger_status(status, dim_map.get(heading)):
                dim_map[heading] = status

        # candidate_id -> {dimension -> assessment score 1..5} (max per dimension).
        assessment_rows = await self._fetcher.fetch_assessment_scores(candidate_round_ids)
        assessment_scores: dict[str, dict[str, float]] = {}
        for row in assessment_rows:
            cid = cr_to_candidate.get(row["candidate_round_id"])
            category = row.get("category_name")
            score = row.get("score")
            if not cid or not category or score is None:
                continue
            dim_map = assessment_scores.setdefault(cid, {})
            score_f = float(score)
            if category not in dim_map or score_f > dim_map[category]:
                dim_map[category] = score_f

        scorecard_count = len(rounds_with_feedback)
        transcript_count = len(
            [cr_id for cr_id in candidate_round_ids if cr_id in transcript_round_ids]
        )

        return ScaffoldData(
            org_id=org_id,
            requisition_id=requisition_id,
            role_title=plan.requisition.role_title,
            must_have_skills=plan.requisition.must_have_skills,
            nice_to_have_skills=plan.requisition.nice_to_have_skills,
            candidate_names=candidate_names,
            round_facts=round_facts,
            rounds_total_by_candidate={cid: rounds_total for cid in candidate_ids},
            assessment_scores=assessment_scores,
            evidence_status=evidence_status,
            feedback_headings=feedback_headings,
            latest_rating_by_candidate=latest_rating_by_candidate,
            scorecard_count=scorecard_count,
            transcript_count=transcript_count,
        )

    @staticmethod
    def _stronger_status(candidate: str, current: str | None) -> bool:
        """True if `candidate` evidence_status outranks `current` (or current is unset).

        A contradiction is the most decision-relevant signal and must never be
        masked by a later 'verified' on the same dimension, so it ranks highest.
        Ordering (highest first): contradicted > verified > supported > partial > none.
        `supported` is a real prod value (addendum §4) and must rank above `partial`/
        `none` so it isn't masked by a weaker row on the same heading.
        """
        rank = {"contradicted": 4, "verified": 3, "supported": 2, "partial": 1, "none": 0}
        if current is None:
            return True
        return rank.get(candidate, -1) > rank.get(current, -1)
