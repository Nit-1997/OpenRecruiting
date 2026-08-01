"""Deterministic JD text cleanup — runs BEFORE any LLM sees the text.

No model calls here: strip control characters, normalize unicode + whitespace,
and cap length. This is the "first sanitize using raw text" step; the guardrail
(injection check) and parser run on this output.
"""
from __future__ import annotations

import re
import unicodedata

MAX_CHARS = 20_000

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INLINE_WS_RE = re.compile(r"[ \t   ]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def sanitize_jd_text(raw: str) -> tuple[str, bool]:
    """Return (clean_text, truncated). `truncated` is True if the cap was hit."""
    if not raw:
        return "", False
    text = unicodedata.normalize("NFKC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub(" ", text)
    text = _INLINE_WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANK_LINES_RE.sub("\n\n", text).strip()
    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS]
    return text, truncated
