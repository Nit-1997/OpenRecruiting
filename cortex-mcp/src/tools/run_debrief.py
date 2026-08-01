"""run_debrief — proxy the stateless Cortex debrief skill, then narrate it.

The intelligence lives in `cortex-backend` (the only service holding both
Neo4j and Supabase). This tool is a thin front door for talent-leader customers:
it POSTs `{org_id, requisition_id, candidate_ids}` to that skill's internal
`POST /api/v1/debrief` endpoint (authenticated with the shared X-Internal-Secret)
and turns the returned `DebriefPacket` JSON into a COMPACT, non-technical text
summary — the recommended candidate, the ranking, the confidence, and the top
risks.

Contract (spec §11 of docs/superpowers/specs/2026-06-07-debrief-agent-design.md):
  * `org_id` is taken from the authenticated session ONLY — never a tool param.
  * The summary HONORS the MCP server instructions: lead with the answer, talk
    to a non-technical user, and NEVER expose internals (org_id, Cypher, tool
    names, HTTP/infra mechanics). Errors degrade to a friendly one-liner and
    never raise — the caller's LLM relays the text verbatim.

Async hygiene (CLAUDE.md Lambda/async rules): the `httpx.AsyncClient` is built
per call and closed in a `finally` — there is NO module-global, loop-bound
client to strand across event loops.
"""
from __future__ import annotations

import httpx
import structlog

from src.auth.context import AuthContext
from src.config.settings import get_settings

logger = structlog.get_logger(__name__)

# A single, friendly fallback for any failure. Deliberately content-free about
# the cause — the MCP instructions forbid debug-narration to the user.
_FRIENDLY_FAILURE = (
    "I'm having trouble pulling that debrief right now — please try again in a moment."
)

# Human-readable phrasing for the packet's enum values. The raw enum strings
# (`strong_hire`, `no_hire`, ...) are an internal code shape; we never surface
# them verbatim.
_VERDICT_PHRASE = {
    "strong_hire": "a strong hire",
    "hire": "a hire",
    "mixed": "a mixed call",
    "no_hire": "not a hire",
}
_CONFIDENCE_PHRASE = {
    "high": "high confidence",
    "medium": "moderate confidence",
    "low": "low confidence",
}


async def run_debrief(
    auth: AuthContext,
    requisition_id: str,
    candidate_ids: list[str],
) -> str:
    """Generate a comparative debrief for a candidate set and summarize it.

    Returns a compact, user-facing text summary. Always returns a string —
    on any failure it returns a friendly message rather than raising.
    """
    if not candidate_ids:
        return (
            "I need a couple of candidates to compare for that role — "
            "which people would you like me to look at?"
        )

    settings = get_settings()
    base = settings.cortex_backend_internal_url.rstrip("/")
    url = f"{base}/api/v1/debrief"
    payload = {
        "org_id": auth.org_id,
        "requisition_id": requisition_id,
        "candidate_ids": list(candidate_ids),
    }

    client = httpx.AsyncClient(timeout=settings.debrief_timeout_seconds)
    try:
        response = await client.post(
            url,
            json=payload,
            headers={"X-Internal-Secret": settings.internal_secret},
        )
        if response.status_code != 200:
            # Log server-side with detail; tell the user nothing about it.
            logger.warning(
                "debrief_proxy_non_200",
                org_id=auth.org_id,
                requisition_id=requisition_id,
                status_code=response.status_code,
            )
            return _FRIENDLY_FAILURE
        packet = response.json()
    except Exception as e:  # network, timeout, JSON decode — all degrade gracefully.
        logger.warning(
            "debrief_proxy_failed",
            org_id=auth.org_id,
            requisition_id=requisition_id,
            error=f"{type(e).__name__}: {e}",
        )
        return _FRIENDLY_FAILURE
    finally:
        try:
            await client.aclose()
        except Exception as close_err:  # pragma: no cover — last-resort guard
            logger.warning("debrief_client_close_failed", error=str(close_err))

    return _format_summary(packet)


def _format_summary(packet: object) -> str:
    """Render a `DebriefPacket` dict into a compact, non-technical summary.

    Defensive against a malformed body: anything missing degrades to the
    friendly fallback rather than raising. Never includes ids or internals.
    """
    if not isinstance(packet, dict):
        return _FRIENDLY_FAILURE

    candidates = packet.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return _FRIENDLY_FAILURE

    # candidates are PRE-RANKED by the skill (index 0 = recommended winner),
    # but sort defensively on `rank` so a reordered body can't mislead.
    ranked = sorted(
        (c for c in candidates if isinstance(c, dict) and c.get("name")),
        key=lambda c: c.get("rank", 999),
    )
    if not ranked:
        return _FRIENDLY_FAILURE

    winner = ranked[0]
    winner_name = str(winner.get("name"))

    lines: list[str] = []

    # 1. Lead with the answer: the recommendation (prefer the LLM-written prose).
    headline = packet.get("headline_recommendation")
    if isinstance(headline, str) and headline.strip():
        lines.append(headline.strip())
    else:
        verdict = _VERDICT_PHRASE.get(str(winner.get("verdict")), "the strongest fit")
        lines.append(f"{winner_name} is the recommended candidate — {verdict}.")

    # 2. Confidence in that recommendation.
    confidence = _CONFIDENCE_PHRASE.get(str(packet.get("confidence")))
    if confidence:
        lines.append(f"This read comes with {confidence}.")

    # 3. The ranking (names + an at-a-glance verdict, no scores/ids).
    if len(ranked) > 1:
        lines.append("")
        lines.append("How they stack up:")
        for cand in ranked:
            name = str(cand.get("name"))
            verdict = _VERDICT_PHRASE.get(str(cand.get("verdict")), "mixed")
            rank = cand.get("rank")
            prefix = f"{rank}. " if isinstance(rank, int) else "- "
            lines.append(f"{prefix}{name} — {verdict}")

    # 4. Top risks (cap at 3 — keep it tight).
    risks = packet.get("risks")
    if isinstance(risks, list):
        top_risks = [str(r).strip() for r in risks if isinstance(r, str) and r.strip()][:3]
        if top_risks:
            lines.append("")
            lines.append("Things to weigh:")
            lines.extend(f"- {risk}" for risk in top_risks)

    return "\n".join(lines).strip() or _FRIENDLY_FAILURE
