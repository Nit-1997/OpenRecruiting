"""Resume (presigned, expiring URL) → plain text. Download is bounded + streamed
so a large file can't blow the worker's memory; PDF/docx parsing reuses the
intake JD `parse_file` helper (pypdf / python-docx). Fail-soft → None everywhere
(a candidate with an unreadable resume still enriches from ATS signals)."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import httpx
import structlog

from app.services.intake.jd_fetch import parse_file

logger = structlog.get_logger(__name__)

_DOWNLOAD_TIMEOUT = 30.0


async def download_resume_bytes(
    url: str, *, max_bytes: int
) -> tuple[bytes, str] | None:
    """Stream-download up to max_bytes. Returns (data, content_type) or None on
    any HTTP error / oversize / network failure."""
    try:
        async with httpx.AsyncClient(
            timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True
        ) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    logger.warning(
                        "resume_download_http_error", status=resp.status_code
                    )
                    return None
                content_type = resp.headers.get("content-type", "")
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        logger.warning("resume_download_too_large", bytes=total)
                        return None
                    chunks.append(chunk)
        return b"".join(chunks), content_type
    except Exception as exc:  # noqa: BLE001 — never hard-fail enrichment on a download
        logger.warning("resume_download_failed", error=str(exc))
        return None


def _filename_from_url(url: str) -> str | None:
    """The Workable attachment carries a null name; the presigned URL path does
    end in the real filename (…/TaylorMarsh_Resume2025.pdf?X-Amz-…) — strip the
    query so parse_file can detect the .pdf/.docx extension."""
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1]
    return name or None


async def parse_resume_text(
    data: bytes, content_type: str, filename: str | None
) -> str | None:
    """CPU-bound PDF/docx/txt parse, offloaded to a thread. Fail-soft → None."""
    try:
        text = await asyncio.to_thread(parse_file, filename, content_type, data)
    except Exception as exc:  # noqa: BLE001 — unsupported type / parse error → degrade
        logger.warning("resume_parse_failed", error=str(exc))
        return None
    text = (text or "").strip()
    return text or None


async def fetch_resume_text(
    url: str, *, filename: str | None = None, max_bytes: int
) -> str | None:
    """Download + extract text. Returns stripped text, or None when the resume
    can't be fetched/parsed/is empty."""
    downloaded = await download_resume_bytes(url, max_bytes=max_bytes)
    if downloaded is None:
        return None
    data, content_type = downloaded
    return await parse_resume_text(data, content_type, filename or _filename_from_url(url))
