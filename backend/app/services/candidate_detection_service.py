"""
Three-tier candidate detection from Recall participant metadata + live
utterances:

  Tier 1 — name match against tracked participants (confidence 0.95)
  Tier 2 — platform signals: in a 2-person call, the non-host/non-tenant
           participant is the candidate (confidence 0.85)
  Tier 3 — Anthropic Claude Haiku on accumulated utterances (variable
           confidence)

Stops at the first tier that produces a result. The LLM tier only runs
when at least N participants have accumulated K chars of utterances —
controlled via CANDIDATE_DETECT_* settings.

Ported from `backend/v1/app/services/candidate_detection_service.py`.
Utterance buffer is delegated to `app.services.recall_webhook.utterances`
so the realtime webhook handler and detection share one source of truth
(DRY).
"""

from __future__ import annotations

import time
from typing import Optional

import httpx

from app.config import get_settings
from app.logging_config import get_logger
from app.services.cal_intel.policy import ConfidenceTier
from app.services.recall_webhook import utterances as utterance_store
from app.services.supabase import (
    get_async_http_client,
    get_supabase_admin_client,
)
from app.utils import names_match, parse_json_response


logger = get_logger(__name__)


# Re-export utterance functions so v1's call sites can move 1:1.
get_utterances = utterance_store.get_utterances
append_utterance = utterance_store.append_utterance
clear_utterances = utterance_store.clear_utterances


# ---------------------------------------------------------------------------
# Tier 1 — name match
# ---------------------------------------------------------------------------


def tier1_name_match(
    candidate_name: str,
    participants: list[dict],
    utterances: dict[str, str],
) -> Optional[dict]:
    """Match the recruiter-supplied candidate name against participant
    names. Only counts if that participant has spoken (utterances exist)
    so we don't tag someone who joined silently."""
    if not candidate_name:
        return None
    for p in participants:
        p_name = p.get("name", "")
        if not p_name:
            continue
        if names_match(candidate_name, p_name):
            pid = str(p.get("id"))
            if pid in utterances and utterances[pid]:
                return {
                    "candidate_participant_id": p["id"],
                    "candidate_name": p_name,
                    "confidence": ConfidenceTier.DETECTION_NAME_MATCH,
                    "reasoning": (
                        f"Name match: '{candidate_name}' matched participant '{p_name}'"
                    ),
                }
    return None


# ---------------------------------------------------------------------------
# Tier 2 — platform signals
# ---------------------------------------------------------------------------


def tier2_platform_signals(participants: list[dict]) -> Optional[dict]:
    """In a 2-person call where exactly one participant is host/tenant
    and the other isn't, the non-host is the candidate."""
    if len(participants) != 2:
        return None

    host_or_tenant: list[dict] = []
    non_host: list[dict] = []
    for p in participants:
        if p.get("is_host") or p.get("is_tenant"):
            host_or_tenant.append(p)
        else:
            non_host.append(p)

    if len(host_or_tenant) == 1 and len(non_host) == 1:
        candidate = non_host[0]
        return {
            "candidate_participant_id": candidate["id"],
            "candidate_name": candidate.get("name", ""),
            "confidence": ConfidenceTier.DETECTION_PLATFORM_SIGNAL,
            "reasoning": (
                "Platform signal: only non-host/non-tenant participant in 2-person call"
            ),
        }
    return None


# ---------------------------------------------------------------------------
# Tier 3 — Claude Haiku
# ---------------------------------------------------------------------------


_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


async def tier3_llm_detection(
    candidate_name: str,
    participants: list[dict],
    utterances: dict[str, str],
) -> Optional[dict]:
    """Ask Claude Haiku to identify the candidate from utterance snippets."""
    settings = get_settings()

    prompt = _build_detection_prompt(candidate_name, participants, utterances, settings)

    try:
        # The pooled async client carries our X-Request-ID via httpx event
        # hooks — same observability story as the rest of v2. We do NOT
        # use it here because the Anthropic API has its own auth scheme
        # and we don't want our request_id leaking to a third party. Use
        # a one-shot client.
        async with httpx.AsyncClient(timeout=30.0) as client:
            llm_start = time.monotonic()
            response = await client.post(
                _ANTHROPIC_URL,
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "content-type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": settings.CANDIDATE_DETECT_MODEL,
                    "max_tokens": 256,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            resp_json = response.json()
            content = resp_json["content"][0]["text"]
            usage = resp_json.get("usage", {})
            logger.info(
                "llm_response",
                extra={
                    "event": "llm_response",
                    "model": settings.CANDIDATE_DETECT_MODEL,
                    "duration_ms": int((time.monotonic() - llm_start) * 1000),
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
                    "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
                },
            )

        result = parse_json_response(content)
        if not _is_valid_detection_result(result, content):
            return None

        result["confidence"] = float(result["confidence"])
        result["candidate_participant_id"] = int(result["candidate_participant_id"])
        return result

    except Exception as e:
        logger.error(f"Detection: LLM call failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_detection(
    recall_bot: dict,
    utterances: dict[str, str],
) -> Optional[dict]:
    """Run tiers in order, return the first hit. Returns None when no
    tier produces a result (detection disabled, no name, not enough
    talkers, LLM failure)."""
    settings = get_settings()
    if not settings.CANDIDATE_DETECT_ENABLED:
        return None

    candidate_name = recall_bot.get("candidate_name", "")
    tracked = recall_bot.get("tracked_participants") or []

    result = tier1_name_match(candidate_name, tracked, utterances)
    if result:
        logger.info(f"Detection: Tier 1 — {result['reasoning']}")
        return result

    result = tier2_platform_signals(tracked)
    if result:
        logger.info(f"Detection: Tier 2 — {result['reasoning']}")
        return result

    # Tier 3 only runs once enough participants have spoken enough.
    qualifying = sum(
        1 for p in tracked
        if str(p.get("id")) in utterances
        and len(utterances[str(p.get("id"))]) >= settings.CANDIDATE_DETECT_CHAR_THRESHOLD
    )
    if qualifying < settings.CANDIDATE_DETECT_MIN_PARTICIPANTS:
        return None

    result = await tier3_llm_detection(candidate_name, tracked, utterances)
    if result:
        logger.info(f"Detection: Tier 3 — {result.get('reasoning', '')}")
        return result

    return None


async def store_detection_result(
    db_id: str,
    result: dict,
    utterances: dict[str, str],
) -> None:
    """Persist detection to recall_bots and flush the in-memory buffer."""
    supabase = get_supabase_admin_client()
    await supabase.table("recall_bots").update({
        "detected_candidate_participant_id": result["candidate_participant_id"],
        "detection_confidence": result["confidence"],
        "detection_reasoning": result.get("reasoning", ""),
        "detection_completed": True,
        "participant_utterances": utterances,
    }).eq("id", db_id).execute_async()
    clear_utterances(db_id)


async def check_retroactive_trigger(recall_bot: dict, result: dict) -> bool:
    """If detection completes AFTER the candidate has already left the
    call, we may have missed the participant-leave drop trigger. Return
    True so the caller can fire it retroactively.
    """
    settings = get_settings()
    candidate_pid = result["candidate_participant_id"]
    confidence = result["confidence"]
    tracked = recall_bot.get("tracked_participants") or []

    candidate_already_left = any(
        p.get("id") == candidate_pid and p.get("left_at") is not None
        for p in tracked
    )
    if (
        candidate_already_left
        and confidence >= settings.CANDIDATE_DETECT_CONFIDENCE_THRESHOLD
    ):
        logger.info(
            f"Detection: candidate pid={candidate_pid} already left "
            f"confidence={confidence} — retroactive trigger"
        )
        return True
    return False


# ---------------------------------------------------------------------------
# private helpers
# ---------------------------------------------------------------------------


def _build_detection_prompt(
    candidate_name: str,
    participants: list[dict],
    utterances: dict[str, str],
    settings,
) -> str:
    lines = []
    for p in participants:
        pid = str(p.get("id"))
        snippet = utterances.get(pid, "")[:settings.CANDIDATE_DETECT_CHAR_THRESHOLD]
        is_host = p.get("is_host", False)
        is_tenant = p.get("is_tenant", False)
        lines.append(
            f'- ID {p.get("id")}, "{p.get("name", "")}" '
            f'(is_host={is_host}, is_tenant={is_tenant}): "{snippet}"'
        )

    joined_lines = "\n".join(lines)
    return (
        f'Identify the CANDIDATE (interviewee) from these meeting participants.\n\n'
        f'Known candidate name: "{candidate_name or "unknown"}"\n\n'
        f'Participants:\n'
        f'{joined_lines}\n\n'
        f'Rules:\n'
        f'- Interviewers ask questions, introduce company, explain structure\n'
        f'- Candidates describe their background, current role, experience\n'
        f'- is_host=true / is_tenant=true = strong interviewer signal\n'
        f'- There is always exactly ONE candidate\n\n'
        f'Return JSON only:\n'
        f'{{"candidate_participant_id": <int>, "candidate_name": "<name>", '
        f'"confidence": <0.0-1.0>, "reasoning": "<brief>"}}'
    )


def _is_valid_detection_result(result, content: str) -> bool:
    """Validate the LLM's JSON shape. Logs and returns False on bad input."""
    required = {"candidate_participant_id", "confidence"}
    if not isinstance(result, dict) or not required.issubset(result.keys()):
        logger.warning(f"Detection: LLM response missing required keys: {content}")
        return False
    if result["candidate_participant_id"] is None or result["confidence"] is None:
        logger.warning(f"Detection: LLM returned null values: {content}")
        return False
    return True
