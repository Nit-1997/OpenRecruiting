"""DebriefReadTools — the templated, in-loop read tools for debrief chat.

Consumes the DebriefPacketResponse body (`debrief_packets.packet`); candidate
membership is derived from `candidates[].candidate_id`.

Each tool is a parameterized query; the LLM NEVER authors Cypher/SQL. The hard
guardrail (spec §3.3, §8): every candidate_id the model passes is validated against
the body's candidates BEFORE any query runs — the LLM cannot pivot to a candidate
outside this debrief. The packet is already org-scoped by the loader, so membership
is the org gate for the Supabase reads. Supabase reads are additionally scoped to
the packet's requisition (a candidate can sit in several of the org's pipelines —
rounds from OTHER roles must never pollute this debrief's answers).

The Cortex seam (`cortex_query`) is a cleaner `(cypher, params) -> rows` adapter the
runner binds over `CortexGapReader` + `mint_cortex_service_token` (token-minting and
SSE/JSON unwrap are the runner's job). Templated Cypher built here always binds
group_id = $org_id, passes values as params, bounds the LIMIT, and uses no brace
subqueries (CALL{}/EXISTS{}/COUNT{}/COLLECT{}) — honoring the MCP validator. The
graph read is best-effort: any exception collapses to {"standings": []}.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

# Bounds that keep an unbounded fetch off the event loop / out of the model context.
_MAX_EXCERPTS = 8
_MAX_GRAPH_ROWS = 10
_MIN_KEYWORD_LEN = 3

CortexQuery = Callable[[str, dict], Awaitable[list[dict]]]

# Cross-candidate competency standing on this role. Every binding carries
# group_id = $org_id; the competency / candidate filters are params, never
# interpolated; bounded LIMIT; no brace subqueries.
_STANDING_CYPHER = """
MATCH (c:Candidate {group_id: $org_id})-[r:RELATES_TO {name: 'STRONG_IN'}]->(comp:Competency {group_id: $org_id})
WHERE ($competency IS NULL OR comp.name = $competency)
  AND ($candidate_ref IS NULL OR c.candidate_ref = $candidate_ref)
RETURN c.name AS candidate, comp.name AS competency
ORDER BY comp.name ASC, candidate ASC
LIMIT $row_limit
"""

def _topic_keywords(topic: str) -> list[str]:
    """Split a topic into lowercase match keywords (>= 3 chars). A segment
    matches if ANY keyword appears, so 'system design tradeoffs' finds segments
    mentioning just 'design' — far more forgiving than the old verbatim
    whole-phrase substring."""
    words = [w for w in re.split(r"[^a-z0-9]+", topic.lower()) if len(w) >= _MIN_KEYWORD_LEN]
    if words:
        return words
    stripped = topic.strip().lower()
    return [stripped] if stripped else []


class DebriefReadTools:
    def __init__(
        self,
        *,
        supabase,
        cortex_query: CortexQuery,
        packet: dict,
        org_id: str,
        requisition_id: str | None = None,
    ) -> None:
        self._db = supabase
        self._cortex_query = cortex_query
        self._packet = packet
        self._org_id = org_id
        self._requisition_id = str(requisition_id) if requisition_id else None
        self._candidate_ids = {
            c["candidate_id"]
            for c in packet.get("candidates", [])
            if c.get("candidate_id")
        }

    async def dispatch(self, name: str, args: dict) -> dict:
        if name == "get_candidate_detail":
            return await self._get_candidate_detail(args)
        if name == "get_transcript_evidence":
            return await self._get_transcript_evidence(args)
        if name == "get_graph_standing":
            return await self._get_graph_standing(args)
        return {"error": f"unknown tool: {name}"}

    def _in_packet(self, candidate_id: str | None) -> bool:
        return candidate_id is not None and candidate_id in self._candidate_ids

    def _in_requisition(self, row: dict) -> bool:
        """Keep only candidate_rounds belonging to this debrief's requisition.
        Unscoped packets (no requisition_id — legacy) keep every row."""
        if not self._requisition_id:
            return True
        round_req = (row.get("rounds") or {}).get("requisition_id")
        return str(round_req) == self._requisition_id

    async def _candidate_rounds(self, candidate_id: str) -> list[dict]:
        result = await (
            self._db.table("candidate_rounds")
            .select("id, status, rating, summary, outcome, rounds(name, requisition_id)")
            .eq("candidate_id", candidate_id)
            .execute_async()
        )
        return [row for row in (result.data or []) if self._in_requisition(row)]

    # ------------------------------------------------------------------ #
    async def _get_candidate_detail(self, args: dict) -> dict:
        candidate_id = args.get("candidate_id")
        if not self._in_packet(candidate_id):
            return {"error": "candidate not in this debrief"}

        rows = await self._candidate_rounds(candidate_id)
        rounds = [
            {
                "round_name": (row.get("rounds") or {}).get("name") or "",
                "status": row.get("status"),
                "rating": row.get("rating"),
                "summary": row.get("summary"),
                "outcome": row.get("outcome"),
            }
            for row in rows
        ]
        return {"candidate_id": candidate_id, "rounds": rounds}

    # ------------------------------------------------------------------ #
    async def _get_transcript_evidence(self, args: dict) -> dict:
        candidate_id = args.get("candidate_id")
        if not self._in_packet(candidate_id):
            return {"error": "candidate not in this debrief"}
        topic = (args.get("topic") or "").strip()
        round_ref = (args.get("round_ref") or "").strip().lower()
        keywords = _topic_keywords(topic)

        rows = await self._candidate_rounds(candidate_id)
        round_name_by_id: dict[str, str] = {}
        for row in rows:
            cr_id = row.get("id")
            if not cr_id:
                continue
            name = (row.get("rounds") or {}).get("name") or ""
            if round_ref and round_ref not in (name.lower(), str(cr_id).lower()):
                continue
            round_name_by_id[cr_id] = name
        if not round_name_by_id:
            return {"candidate_id": candidate_id, "excerpts": []}

        transcripts_result = await (
            self._db.table("transcripts")
            .select("candidate_round_id, segments")
            .in_("candidate_round_id", list(round_name_by_id))
            .execute_async()
        )
        excerpts: list[dict] = []
        for transcript in transcripts_result.data or []:
            round_name = round_name_by_id.get(transcript.get("candidate_round_id"), "")
            for segment in transcript.get("segments") or []:
                if len(excerpts) >= _MAX_EXCERPTS:
                    break
                text = segment.get("text") or ""
                lowered = text.lower()
                if keywords and not any(k in lowered for k in keywords):
                    continue
                excerpts.append(
                    {
                        "round_name": round_name,
                        "speaker": segment.get("speaker") or "",
                        "text": text,
                    }
                )
            if len(excerpts) >= _MAX_EXCERPTS:
                break
        out = {"candidate_id": candidate_id, "excerpts": excerpts}
        if not excerpts and keywords:
            out["hint"] = (
                "no transcript segments matched those keywords; try a single "
                "shorter keyword or drop the round filter"
            )
        return out

    # ------------------------------------------------------------------ #
    async def _get_graph_standing(self, args: dict) -> dict:
        candidate_id = args.get("candidate_id")
        if candidate_id is not None and not self._in_packet(candidate_id):
            return {"error": "candidate not in this debrief"}
        competency = args.get("competency")

        params = {
            "org_id": self._org_id,
            "competency": competency or None,
            "candidate_ref": candidate_id or None,
            "row_limit": _MAX_GRAPH_ROWS,
        }
        try:
            rows = await self._cortex_query(_STANDING_CYPHER, params)
        except Exception as exc:  # noqa: BLE001 — best-effort graph read
            logger.warning("debrief_graph_standing_failed", error=str(exc))
            return {"standings": []}
        return {"standings": rows or []}
