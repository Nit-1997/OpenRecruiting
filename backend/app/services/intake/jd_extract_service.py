"""Orchestrate the JD extract pipeline: acquire → sanitize → guardrail → parse.

acquire  — URL (SSRF-guarded) / file / pasted text  →  raw text
sanitize — deterministic cleanup (no LLM)
guardrail — injection check; trips → quarantine (status 'rejected')
parse     — structured extraction + formatted markdown

Returns a plain dict the router maps to the response schema. Fetch/parse errors
propagate as JdFetchError subtypes for the router to translate to HTTP codes.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.services.intake.jd_fetch import (
    JdFetchError,
    SsrfBlockedError,
    fetch_url_text,
    find_first_url,
    parse_file,
)
from app.services.intake.jd_guardrail import check_injection
from app.services.intake.jd_parser import format_jd, parse_jd
from app.services.intake.jd_sanitize import sanitize_jd_text

logger = structlog.get_logger(__name__)


def _empty(source: str, truncated: bool = False) -> dict[str, Any]:
    return {
        "status": "empty",
        "source": source,
        "formatted_jd": "",
        "structured": None,
        "flags": {"injection_detected": False, "reason": None, "truncated": truncated},
    }


async def extract_jd(
    *,
    llm: Any,
    model: str,
    text: str | None = None,
    file: tuple[str | None, str | None, bytes] | None = None,
) -> dict[str, Any]:
    """One box: free text (URL auto-detected + fetched) and/or an uploaded file.

    A URL inside `text` is fetched (SSRF-guarded) and its content is COMBINED with
    the rest of the pasted context — so the recruiter can paste a posting link plus
    notes. SSRF-blocked URLs hard-fail; a failed/empty fetch (e.g. expired posting)
    soft-falls-back to the pasted text so they're never stuck.
    """
    parts: list[str] = []
    source = "text"

    # 1a. file → text. parse_file is CPU-bound (pypdf/python-docx/bs4) — offload
    # to a thread so a large document doesn't block the event loop.
    if file is not None:
        filename, content_type, data = file
        parts.append(await asyncio.to_thread(parse_file, filename, content_type, data))
        source = "file"

    # 1b. free text → detect + fetch a URL, keep the surrounding context too
    if text and text.strip():
        detected = find_first_url(text)
        if detected:
            source = "url"
            try:
                fetched = await fetch_url_text(detected)
                if fetched.strip():
                    parts.append(fetched)
            except SsrfBlockedError:
                raise  # security — surface as 400
            except JdFetchError as exc:
                logger.warning("jd_url_fetch_soft_failed", url=detected, error=str(exc))
        parts.append(text)

    raw = "\n\n".join(p for p in parts if p and p.strip())

    # 2. deterministic sanitize
    clean, truncated = sanitize_jd_text(raw)
    if not clean.strip():
        return _empty(source, truncated)

    # 3. guardrail — quarantine on a positive injection verdict
    guard = await check_injection(llm, model, clean)
    if guard["injection_detected"]:
        logger.warning("jd_injection_quarantined", source=source, reason=guard.get("reason"))
        return {
            "status": "rejected",
            "source": source,
            "formatted_jd": "",
            "structured": None,
            "flags": {
                "injection_detected": True,
                "reason": guard.get("reason") or "The text contained instructions aimed at the AI.",
                "truncated": truncated,
            },
        }

    # 4. parse → structured + formatted
    structured = await parse_jd(llm, model, clean)
    if not structured:
        return _empty(source, truncated)
    formatted = format_jd(structured)
    if not formatted:
        return _empty(source, truncated)

    return {
        "status": "ok",
        "source": source,
        "formatted_jd": formatted,
        "structured": structured,
        "flags": {"injection_detected": False, "reason": None, "truncated": truncated},
    }
