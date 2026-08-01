"""Handler for the mark_status tool. Only mutates the status field."""

from __future__ import annotations

from typing import Any

import structlog

from intake_core.persistence import update_current_answers, aupdate_current_answers
from intake_core.questions import INTAKE_QUESTIONS

logger = structlog.get_logger(__name__)

_VALID_QIDS = {q["id"] for q in INTAKE_QUESTIONS}
_VALID_STATUS = {"untouched", "needs_probe", "discussed", "validated", "skipped"}


def handle_mark_status(client, session_id: str, args: dict[str, Any]) -> dict[str, Any]:
    qid = args.get("qid")
    status = args.get("status")
    if qid not in _VALID_QIDS:
        return {"ok": False, "error": f"unknown qid: {qid}"}
    if status not in _VALID_STATUS:
        return {"ok": False, "error": f"invalid status: {status}"}

    patch = {qid: {"status": status}}
    try:
        update_current_answers(client, session_id, patch)
    except Exception as e:
        logger.exception("mark_status_failed", session_id=session_id, qid=qid)
        return {"ok": False, "error": str(e)[:200]}

    logger.info("mark_status_applied", session_id=session_id, qid=qid, status=status)
    return {"ok": True, "qid": qid, "status": status}


async def ahandle_mark_status(client, session_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """Async variant — for the FastAPI text path (SupabaseAdminClient)."""
    qid = args.get("qid")
    status = args.get("status")
    if qid not in _VALID_QIDS:
        return {"ok": False, "error": f"unknown qid: {qid}"}
    if status not in _VALID_STATUS:
        return {"ok": False, "error": f"invalid status: {status}"}

    patch = {qid: {"status": status}}
    try:
        await aupdate_current_answers(client, session_id, patch)
    except Exception as e:
        logger.exception("mark_status_failed", session_id=session_id, qid=qid)
        return {"ok": False, "error": str(e)[:200]}

    logger.info("mark_status_applied", session_id=session_id, qid=qid, status=status)
    return {"ok": True, "qid": qid, "status": status}
