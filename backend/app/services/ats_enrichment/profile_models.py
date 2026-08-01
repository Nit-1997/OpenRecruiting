"""The role-agnostic structured profile extracted from a resume. Industry-neutral
on purpose — Workable customers span finance/sales/ops, not just engineering, so
there is NO tech-shaped schema (no languages/frameworks/databases split)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkEntry(BaseModel):
    title: str | None = None
    company: str | None = None
    start: str | None = None
    end: str | None = None
    is_current: bool = False
    highlights: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    degree: str | None = None
    field: str | None = None
    institution: str | None = None
    year: str | None = None


class ResumeProfile(BaseModel):
    summary: str = ""
    headline: str | None = None
    total_experience_years: float = 0.0
    seniority: str | None = None
    skills: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    work_history: list[WorkEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)  # linkedin / github / portfolio
