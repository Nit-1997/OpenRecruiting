"""Handler for the update_answer tool. Called by both voice agent and text agent.

Writes a JSONB patch into intake_sessions.current_answers via the
intake_sessions_merge_answers RPC (atomic merge — no read-modify-write race).
"""

from __future__ import annotations

from typing import Any

import structlog

from intake_core.persistence import update_current_answers, aupdate_current_answers
from intake_core.questions import INTAKE_QUESTIONS

logger = structlog.get_logger(__name__)

_VALID_QIDS = {q["id"] for q in INTAKE_QUESTIONS}
_VALID_CONFIDENCE = {"none", "low", "medium", "high"}
_VALID_STATUS = {"untouched", "needs_probe", "discussed", "validated", "skipped"}


def _build_patch(qid: str, text: str, confidence: str, status: str, turn_idx: int) -> dict:
    return {
        qid: {
            "text": text,
            "extraction_confidence": confidence,
            "status": status,
            "turns_addressed": [turn_idx],
            "sources": [f"turn:{turn_idx}"],
        }
    }


def _validate_args(args: dict[str, Any]) -> tuple[str | None, str | None, str | None, str, str | None]:
    """Returns (qid, text, confidence, status, error_msg)."""
    qid = args.get("qid")
    text = args.get("text")
    confidence = args.get("confidence")
    status = args.get("status", "discussed")
    if qid not in _VALID_QIDS:
        return qid, text, confidence, status, f"unknown qid: {qid}"
    if not isinstance(text, str):
        return qid, text, confidence, status, "text must be a string"
    if confidence not in _VALID_CONFIDENCE:
        return qid, text, confidence, status, f"invalid confidence: {confidence}"
    if status not in _VALID_STATUS:
        return qid, text, confidence, status, f"invalid status: {status}"
    return qid, text, confidence, status, None


def handle_update_answer(
    client,
    session_id: str,
    args: dict[str, Any],
    turn_idx: int,
) -> dict[str, Any]:
    """Validate args and write the JSONB patch. Returns {ok: bool, error?: str}."""
    qid, text, confidence, status, err = _validate_args(args)
    if err:
        return {"ok": False, "error": err}

    patch = _build_patch(qid, text, confidence, status, turn_idx)
    try:
        update_current_answers(client, session_id, patch)
    except Exception as e:
        logger.exception("update_answer_failed", session_id=session_id, qid=qid)
        return {"ok": False, "error": str(e)[:200]}

    logger.info("update_answer_applied", session_id=session_id, qid=qid, status=status)
    return {"ok": True, "qid": qid, "status": status}


async def ahandle_update_answer(
    client,
    session_id: str,
    args: dict[str, Any],
    turn_idx: int,
) -> dict[str, Any]:
    """Async variant — for the FastAPI text path (SupabaseAdminClient)."""
    qid, text, confidence, status, err = _validate_args(args)
    if err:
        return {"ok": False, "error": err}

    patch = _build_patch(qid, text, confidence, status, turn_idx)
    try:
        await aupdate_current_answers(client, session_id, patch)
    except Exception as e:
        logger.exception("update_answer_failed", session_id=session_id, qid=qid)
        return {"ok": False, "error": str(e)[:200]}

    logger.info("update_answer_applied", session_id=session_id, qid=qid, status=status)
    return {"ok": True, "qid": qid, "status": status}
