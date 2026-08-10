"""Schemas for POST /intake/jd/extract — JD URL/file/text → formatted JD."""
from __future__ import annotations

from pydantic import BaseModel


class JdStructured(BaseModel):
    title: str | None = None
    location: str | None = None
    summary: str | None = None
    responsibilities: list[str] = []
    must_haves: list[str] = []
    nice_to_haves: list[str] = []


class JdFlags(BaseModel):
    injection_detected: bool = False
    reason: str | None = None
    truncated: bool = False
    # The injection guardrail returned no usable verdict and was failed open, so
    # injection_detected=False above means "not rejected", not "checked and clean".
    guardrail_errored: bool = False


class JdExtractResponse(BaseModel):
    # "ok" | "rejected" (injection) | "empty" (no text / extraction failed)
    status: str
    source: str  # "text" | "url" | "file"
    formatted_jd: str = ""
    structured: JdStructured | None = None
    flags: JdFlags = JdFlags()
