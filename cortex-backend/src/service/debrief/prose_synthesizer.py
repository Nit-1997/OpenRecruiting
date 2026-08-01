"""ProseSynthesizer — the single bounded §7 LLM pass: spine in, PROSE out.

LLM ACCESS PATTERN (reused from `ConceptExtractor`, the existing cortex-backend
LLM path): inject a `ConceptExtractor` and call
`await self._extractor.extract(text=<compact spine JSON>, system_prompt=<§7 prompt>)`.
`extract` returns a parsed JSON dict (OpenAI JSON mode, temperature 0.0) and
returns `{}` on invalid JSON — so a failed call degrades naturally to the
deterministic fallback. The LLM NEVER alters a score/rank/verdict/vote/evidence;
it only writes/polishes prose grounded in the provided spine. Output is validated
(every referenced candidate_id/dimension must exist in the spine); any invalid or
missing field falls back to a deterministic template, never raising.

DESIGN: `synthesize` orchestrates three private stages — `_build_spine_payload`
(compact JSON in), `_extract` (the one guarded LLM call), and per-field validators
that each fall back to a deterministic template (`_template_*`). The result is
ALWAYS a complete, valid `ProseBundle`; `synthesize` MUST NEVER RAISE.
"""

from __future__ import annotations

import json

import structlog

from src.model.debrief import (
    CandidateSpine,
    DebriefSpine,
    NextStep,
    ProseBundle,
)
from src.service.concept_extractor import ConceptExtractor

logger = structlog.get_logger(__name__)


class ProseSynthesizer:
    """One LLM call to narrate the deterministic spine, with cross-reference
    validation and a deterministic-template fallback (fail-soft, never a 500)."""

    def __init__(self, extractor: ConceptExtractor) -> None:
        self._extractor = extractor

    # ------------------------------------------------------------------ public
    async def synthesize(self, spine: DebriefSpine) -> ProseBundle:
        """§7: build the compact spine prompt, make ONE LLM call, validate the
        returned prose against the spine, and assemble a complete `ProseBundle`.
        On any failure (exception / invalid JSON / hallucinated id), fall back to
        deterministic templates for the affected fields — always returns a
        complete bundle, never raises."""
        llm = await self._extract(spine)
        return ProseBundle(
            per_candidate=self._validate_per_candidate(spine, llm.get("per_candidate")),
            headline_recommendation=self._validate_headline(spine, llm.get("headline_recommendation")),
            risks=self._validate_risks(spine, llm.get("risks")),
            next_steps=self._validate_next_steps(spine, llm.get("next_steps")),
            theme_labels=self._validate_theme_labels(spine, llm.get("theme_labels")),
            matrix_notes=self._validate_matrix_notes(spine, llm.get("matrix_notes")),
        )

    # ------------------------------------------------------------------ LLM call
    async def _extract(self, spine: DebriefSpine) -> dict:
        """The single guarded LLM call. Returns `{}` on ANY failure so every
        downstream validator drops to its deterministic template."""
        try:
            payload = self._build_spine_payload(spine)
            result = await self._extractor.extract(
                text=json.dumps(payload, separators=(",", ":")),
                system_prompt=self._SYSTEM_PROMPT,
            )
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 — fail-soft is the contract
            logger.warning("debrief_prose_extract_failed", error=str(exc), req=spine.requisition_id)
            return {}

    def _build_spine_payload(self, spine: DebriefSpine) -> dict:
        """Compact, grounded JSON of the spine — scores/ranks/verdicts/votes,
        strengths/concerns, themes, dimensions, risks — enough for prose, no
        transcripts.

        Addendum §6: surface the Cortex-only signals (enrichment tier, per-candidate
        corroboration/contradiction counts) so the model can weave graph context
        into headlines/recommendations/risks for graph-enriched packets. The
        themes + risks already carry the trait clustering + contradictions."""
        return {
            "role_title": spine.role_title,
            "overall_verdict": spine.overall_verdict,
            "confidence": spine.confidence,
            "enrichment_tier": spine.enrichment_tier,
            "dimensions": spine.dimensions,
            "must_have_dimensions": sorted(spine.must_have_dimensions),
            "candidates": [
                {
                    "candidate_id": c.candidate_id,
                    "name": c.name,
                    "rank": c.rank,
                    "verdict": c.verdict,
                    "aggregate_score": c.aggregate_score,
                    "aggregate_insufficient": c.aggregate_insufficient,
                    "rounds_completed": c.rounds_completed,
                    "rounds_total": c.rounds_total,
                    "top_strengths": c.top_strengths,
                    "top_concerns": c.top_concerns,
                    "cells": {cell.dimension: cell.value for cell in c.cells if cell.value is not None},
                    "panel_votes": [
                        {"panelist": v.panelist, "role": v.panelist_role, "vote": v.vote}
                        for v in c.panel_votes
                    ],
                    # Cortex-only signals (addendum §6): independent cross-round
                    # convergence (corroboration) and cross-round conflict.
                    "corroboration_count": c.corroboration_count,
                    "contradiction_count": c.contradiction_count,
                }
                for c in spine.candidates
            ],
            "themes": [
                {"index": i, "label": t.label, "tone": t.tone, "weight": t.weight}
                for i, t in enumerate(spine.themes)
            ],
            "risks": spine.risks,
        }

    # ------------------------------------------------------------ validators
    def _validate_per_candidate(self, spine: DebriefSpine, raw) -> dict[str, dict[str, str]]:
        """Every candidate in the spine gets a complete `{headline, recommendation}`.
        LLM entries for unknown candidate_ids are dropped; missing/blank fields per
        known candidate fall back to a deterministic template."""
        llm_by_cid = raw if isinstance(raw, dict) else {}
        out: dict[str, dict[str, str]] = {}
        for cand in spine.candidates:
            entry = llm_by_cid.get(cand.candidate_id)
            entry = entry if isinstance(entry, dict) else {}
            headline = _clean(entry.get("headline")) or self._template_headline(cand)
            recommendation = _clean(entry.get("recommendation")) or self._template_recommendation(cand)
            out[cand.candidate_id] = {"headline": headline, "recommendation": recommendation}
        return out

    def _validate_headline(self, spine: DebriefSpine, raw) -> str:
        return _clean(raw) or self._template_headline_recommendation(spine)

    def _validate_risks(self, spine: DebriefSpine, raw) -> list[str]:
        if isinstance(raw, list):
            cleaned = [_clean(r) for r in raw if _clean(r)]
            if cleaned:
                return cleaned
        return self._template_risks(spine)

    def _validate_next_steps(self, spine: DebriefSpine, raw) -> list[NextStep]:
        if isinstance(raw, list):
            steps: list[NextStep] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                label = _clean(item.get("label"))
                if not label:
                    continue
                steps.append(
                    NextStep(
                        label=label,
                        owner=_clean(item.get("owner")) or None,
                        due=_clean(item.get("due")) or None,
                    )
                )
            if steps:
                return steps
        return self._template_next_steps(spine)

    def _validate_theme_labels(self, spine: DebriefSpine, raw) -> dict[int, str]:
        """Keys are theme indices into `spine.themes`. LLM returns string keys
        (JSON) — coerce to int, drop out-of-range/non-int, template the rest."""
        llm_by_idx: dict[int, str] = {}
        if isinstance(raw, dict):
            for key, val in raw.items():
                idx = _as_index(key)
                if idx is None or not (0 <= idx < len(spine.themes)):
                    continue
                label = _clean(val)
                if label:
                    llm_by_idx[idx] = label
        return {i: llm_by_idx.get(i, theme.label) for i, theme in enumerate(spine.themes)}

    def _validate_matrix_notes(self, spine: DebriefSpine, raw) -> dict[str, str]:
        """One note per spine dimension. LLM notes for unknown dimensions are
        dropped; known dimensions with no/blank LLM note get a templated note."""
        llm_by_dim = raw if isinstance(raw, dict) else {}
        out: dict[str, str] = {}
        for dim in spine.dimensions:
            note = _clean(llm_by_dim.get(dim))
            out[dim] = note or self._template_matrix_note(spine, dim)
        return out

    # ------------------------------------------------------------ templates
    def _template_headline(self, cand: CandidateSpine) -> str:
        verdict = cand.verdict.replace("_", " ")
        strongest = self._strongest_dimension(cand)
        if strongest:
            return f"{cand.name}: {verdict}, strongest in {strongest}."
        return f"{cand.name}: {verdict}."

    def _template_recommendation(self, cand: CandidateSpine) -> str:
        verdict = cand.verdict.replace("_", " ")
        parts = [f"Overall {verdict} ({cand.aggregate_score:.1f}/4)."]
        if cand.top_strengths:
            parts.append("Strengths: " + ", ".join(cand.top_strengths[:3]) + ".")
        if cand.top_concerns:
            parts.append("Watch: " + ", ".join(cand.top_concerns[:3]) + ".")
        return " ".join(parts)

    def _template_headline_recommendation(self, spine: DebriefSpine) -> str:
        verdict = spine.overall_verdict.replace("_", " ")
        if spine.candidates:
            top = spine.candidates[0]
            return (
                f"Recommended: {top.name} ({verdict}, {top.aggregate_score:.1f}/4) "
                f"for {spine.role_title}."
            )
        return f"No candidate clears the bar for {spine.role_title} ({verdict})."

    def _template_risks(self, spine: DebriefSpine) -> list[str]:
        if spine.risks:
            return list(spine.risks)
        return ["No material decision risks surfaced from the available evidence."]

    def _template_next_steps(self, spine: DebriefSpine) -> list[NextStep]:
        if spine.candidates:
            return [
                NextStep(label=f"Review the debrief packet for {spine.role_title} with the panel."),
                NextStep(label=f"Confirm next action for {spine.candidates[0].name}."),
            ]
        return [NextStep(label=f"Source additional candidates for {spine.role_title}.")]

    def _template_matrix_note(self, spine: DebriefSpine, dimension: str) -> str:
        scored = [
            (c.name, cell.value)
            for c in spine.candidates
            for cell in c.cells
            if cell.dimension == dimension and cell.value is not None
        ]
        if not scored:
            return f"No scored evidence on {dimension}."
        leader_name, leader_value = max(scored, key=lambda pair: pair[1])
        must_have = " (must-have)" if dimension in spine.must_have_dimensions else ""
        return f"{leader_name} leads on {dimension}{must_have} at {leader_value:.1f}/4."

    @staticmethod
    def _strongest_dimension(cand: CandidateSpine) -> str | None:
        scored = [cell for cell in cand.cells if cell.value is not None]
        if not scored:
            return None
        return max(scored, key=lambda cell: cell.value).dimension

    # ------------------------------------------------------------ prompt
    _SYSTEM_PROMPT = (
        "You are the prose writer for a hiring-debrief decision packet. You receive a "
        "deterministic SPINE as JSON: per-candidate scores, ranks, verdicts, panel votes, "
        "strengths, concerns; a list of dimensions; cross-candidate themes; and risk seeds. "
        "Your ONLY job is to write clear, grounded, recruiter-facing PROSE.\n\n"
        "HARD RULES:\n"
        "1. NEVER invent, alter, or contradict any score, rank, verdict, vote, or piece of "
        "evidence. The spine is the single source of truth — narrate it, never override it.\n"
        "2. Reference ONLY candidate_ids that appear in the spine and ONLY dimensions listed "
        "in the spine. Do not introduce new candidates, dimensions, themes, or facts.\n"
        "3. Be concise and decision-oriented. Headlines are one sentence; recommendations are "
        "1-2 sentences; matrix notes are a short clause.\n"
        "4. Ground every statement in the provided strengths, concerns, scores, and risks.\n"
        "5. When `enrichment_tier` is `graph_enriched`, WEAVE the Cortex graph context "
        "into the prose: cite corroboration (independent cross-round convergence, the "
        "`corroboration_count`) as a confidence signal, call out `contradiction_count` "
        "conflicts as risks, and reference the trait `themes`. For a `baseline` packet, "
        "stay grounded in the deterministic scores/votes/risks and do NOT imply graph "
        "corroboration that isn't there.\n\n"
        "Return a JSON object with EXACTLY this shape (prose strings only):\n"
        "{\n"
        '  "per_candidate": { "<candidate_id>": { "headline": str, "recommendation": str } },\n'
        '  "headline_recommendation": str,\n'
        '  "risks": [str],\n'
        '  "next_steps": [ { "label": str, "owner": str|null, "due": str|null } ],\n'
        '  "theme_labels": { "<theme_index>": str },\n'
        '  "matrix_notes": { "<dimension>": str }\n'
        "}\n"
        "theme_index is the integer index of the theme in the spine's themes array. "
        "Keys in matrix_notes must be exact dimension strings from the spine. "
        "Output JSON only — no prose outside the JSON object."
    )


def _clean(value) -> str:
    """Coerce to a trimmed string; non-strings and blanks become ''."""
    if not isinstance(value, str):
        return ""
    return value.strip()


def _as_index(key) -> int | None:
    """Coerce a JSON object key (str/int) to an int theme index, or None."""
    if isinstance(key, bool):
        return None
    if isinstance(key, int):
        return key
    if isinstance(key, str):
        try:
            return int(key.strip())
        except ValueError:
            return None
    return None
